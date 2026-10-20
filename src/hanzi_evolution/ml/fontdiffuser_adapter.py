"""FontDiffuser 官方权重的隔离实验适配器；外部代码位于 thirdparty/fontdiffuser。"""

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset, Subset, WeightedRandomSampler

ROOT = Path(__file__).resolve().parents[3]
UPSTREAM = ROOT / "thirdparty/fontdiffuser"
SIZE = 96
PREPROCESS = "fontdiffuser-alpha-bbox-white-v1"
OFFICIAL_SHA = {
    "unet.pth": "6bde1920ac8d843edbfffa6e6befedc5da39f753b927ce272cfc85cf99dcbfdb",
    "style_encoder.pth": "82eb56abc37ebf7e662d1141a45d8a54ad4bc0ee8aa749c4bb7bc7bddb6cca46",
    "content_encoder.pth": "e5b52582473579031bd0f935abbb9a3e5cb3727dccc25e75f77d1f41d3cbb3ff",
}


def _upstream():
    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))
    from configs.fontdiffuser import get_parser
    from src import (FontDiffuserModel, FontDiffuserModelDPM, FontDiffuserDPMPipeline,
                     build_content_encoder, build_ddpm_scheduler, build_style_encoder,
                     build_unet)
    return SimpleNamespace(get_parser=get_parser, FontDiffuserModel=FontDiffuserModel,
                           FontDiffuserModelDPM=FontDiffuserModelDPM,
                           FontDiffuserDPMPipeline=FontDiffuserDPMPipeline,
                           build_content_encoder=build_content_encoder,
                           build_ddpm_scheduler=build_ddpm_scheduler,
                           build_style_encoder=build_style_encoder, build_unet=build_unet)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"无效图片路径：{relative}")
    return path


def _font(row):
    return parse_qs(urlparse(row["target_url"]).query).get("font", [""])[0]


def load_examples(manifest, data_root):
    """风格参考只取 train 中相同实际字库的其他字头。"""
    content = Path(manifest).read_bytes()
    rows = [json.loads(line) for line in content.splitlines() if line.strip()]
    splits = {}
    pool = defaultdict(list)
    for row in rows:
        character = row["character"]
        split = row["split"]
        if split not in {"train", "val", "test"}:
            raise ValueError(f"未知 split：{split}")
        if character in splits and splits[character] != split:
            raise ValueError(f"字头跨 split：{character}")
        splits[character] = split
        font = _font(row)
        if font and split == "train":
            pool[(row["target_style"], font)].append(row)
    examples = []
    skipped = Counter()
    for row in rows:
        font = _font(row)
        refs = [ref for ref in pool[(row["target_style"], font)]
                if ref["character"] != row["character"]]
        if not font or not refs:
            skipped[row["target_style"]] += 1
            continue
        for key in ("source_image", "target_image"):
            path = _path(data_root, row[key])
            expected = row.get(key.replace("_image", "_sha256"))
            if expected and _sha(path) != expected:
                raise ValueError(f"图片哈希不匹配：{path}")
        examples.append({"row": row, "font": font, "refs": refs})
    if not any(item["row"]["split"] == "train" for item in examples):
        raise ValueError("没有可训练配对")
    return examples, hashlib.sha256(content).hexdigest(), dict(skipped)


def glyph_tensor(path):
    """官方模型使用 96×96 RGB、[-1,1]；透明字形合成到白底。"""
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    alpha = image.getchannel("A")
    box = alpha.getbbox()
    if box is None:
        raise ValueError(f"空白字形图：{path}")
    image = image.crop(box)
    width, height = image.size
    scale = (SIZE - 8) / max(width, height)
    image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))),
                         Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (SIZE, SIZE), "white")
    canvas.paste(image.convert("RGB"), ((SIZE - image.width) // 2,
                                         (SIZE - image.height) // 2), image.getchannel("A"))
    pixels = np.asarray(canvas, dtype=np.float32).copy() / 127.5 - 1.0
    return torch.from_numpy(pixels).permute(2, 0, 1)


class FontPairs(Dataset):
    def __init__(self, examples, data_root, split, random_references=False,
                 content_mode="modern"):
        self.data_root = Path(data_root)
        self.random_references = random_references
        self.content_mode = content_mode
        pool = [item for item in examples if item["row"]["split"] == split]
        self.prototypes = {}
        if content_mode == "prototype":
            for item in pool:
                row = item["row"]
                candidates = [other for other in pool
                              if other["row"]["character"] == row["character"]
                              and other["row"]["target_style"] == row["target_style"]
                              and other["font"] != item["font"]
                              and other["row"]["target_sha256"] != row["target_sha256"]]
                if candidates:
                    self.prototypes[row["pair_id"]] = candidates
            self.examples = [item for item in pool
                             if item["row"]["pair_id"] in self.prototypes]
        elif content_mode == "modern":
            self.examples = pool
        else:
            raise ValueError(f"未知内容模式：{content_mode}")

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, index):
        item = self.examples[index]
        row = item["row"]
        ref = random.choice(item["refs"]) if self.random_references else item["refs"][0]
        if self.content_mode == "prototype":
            candidates = self.prototypes[row["pair_id"]]
            prototype = random.choice(candidates) if self.random_references else candidates[0]
            source_image = prototype["row"]["target_image"]
        else:
            source_image = row["source_image"]
        return {
            "source": glyph_tensor(_path(self.data_root, source_image)),
            "reference": glyph_tensor(_path(self.data_root, ref["target_image"])),
            "target": glyph_tensor(_path(self.data_root, row["target_image"])),
        }


def load_model(ckpt_dir, device, finetuned_unet=None):
    ckpt_dir = Path(ckpt_dir)
    for filename, expected in OFFICIAL_SHA.items():
        path = ckpt_dir / filename
        if _sha(path) != expected:
            raise ValueError(f"官方权重 SHA-256 不匹配：{path}")
    upstream = _upstream()
    model_args = upstream.get_parser().parse_args([])
    model_args.style_image_size = (SIZE, SIZE)
    model_args.content_image_size = (SIZE, SIZE)
    unet = upstream.build_unet(model_args)
    style_encoder = upstream.build_style_encoder(model_args)
    content_encoder = upstream.build_content_encoder(model_args)
    unet.load_state_dict(torch.load(ckpt_dir / "unet.pth", map_location="cpu"))
    style_encoder.load_state_dict(torch.load(ckpt_dir / "style_encoder.pth", map_location="cpu"))
    content_encoder.load_state_dict(torch.load(ckpt_dir / "content_encoder.pth", map_location="cpu"))
    if finetuned_unet is not None:
        saved = torch.load(finetuned_unet, map_location="cpu")
        unet.load_state_dict(saved["unet"])
    model = upstream.FontDiffuserModel(unet, style_encoder, content_encoder).to(device)
    scheduler = upstream.build_ddpm_scheduler(model_args)
    return model, scheduler, upstream


def _loss(model, scheduler, batch, device):
    source = batch["source"].to(device)
    reference = batch["reference"].to(device)
    target = batch["target"].to(device)
    noise = torch.randn_like(target)
    timesteps = torch.randint(scheduler.config.num_train_timesteps, (len(target),), device=device)
    noisy = scheduler.add_noise(target, noise, timesteps)
    prediction, offset = model(noisy, timesteps, reference, source,
                               content_encoder_downsample_size=3)
    return F.mse_loss(prediction.float(), noise.float()) + 0.25 * offset


def _validation(model, scheduler, dataset, device, limit, seed):
    if not dataset:
        return None
    torch.manual_seed(seed)
    model.eval()
    by_style = defaultdict(dict)
    for item in dataset.examples:
        row = item["row"]
        by_style[row["target_style"]].setdefault(row["character"], item)
    candidates = {style: list(chars.values()) for style, chars in sorted(by_style.items())}
    selected = []
    while len(selected) < limit and any(candidates.values()):
        for style in candidates:
            if candidates[style] and len(selected) < limit:
                selected.append(candidates[style].pop(0))
    loader = DataLoader(Subset(dataset, [dataset.examples.index(item) for item in selected]),
                        batch_size=1)
    losses = []
    with torch.no_grad():
        for batch in loader:
            losses.append(_loss(model, scheduler, batch, device).item())
    model.unet.train()
    return sum(losses) / len(losses)


def train(args):
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用")
    examples, digest, skipped = load_examples(args.manifest, args.data_root)
    train_data = FontPairs(examples, args.data_root, "train", random_references=True,
                           content_mode=args.content_mode)
    val_data = FontPairs(examples, args.data_root, "val",
                         content_mode=args.content_mode)
    if len(train_data) == 0 or len(val_data) == 0:
        raise ValueError("清单缺少可用 train/val 配对")
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"不会覆盖已有实验目录：{output}")
    output.mkdir(parents=True)
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = torch.device(args.device)
    model, scheduler, _ = load_model(args.ckpt_dir, device)
    model.style_encoder.requires_grad_(False)
    model.content_encoder.requires_grad_(False)
    model.style_encoder.eval()
    model.content_encoder.eval()
    optimizer = torch.optim.AdamW(model.unet.parameters(), lr=args.learning_rate)
    style_counts = Counter(item["row"]["target_style"] for item in train_data.examples)
    weights = [1.0 / style_counts[item["row"]["target_style"]]
               for item in train_data.examples]
    sampler = WeightedRandomSampler(weights, num_samples=len(train_data), replacement=True)
    loader = DataLoader(train_data, batch_size=args.batch_size, sampler=sampler, num_workers=0)
    iterator = iter(loader)
    config = {"preprocess": PREPROCESS, "content_mode": args.content_mode,
              "manifest_sha256": digest,
              "official_sha256": OFFICIAL_SHA, "train_pairs": len(train_data),
              "val_pairs": len(val_data), "skipped_pairs": skipped,
              "batch_size": args.batch_size, "learning_rate": args.learning_rate,
              "seed": args.seed, "frozen": ["style_encoder", "content_encoder"],
              "style_sampling": "inverse_frequency"}
    (output / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    best_val = float("inf")
    with (output / "metrics.jsonl").open("w") as log:
        for step in range(1, args.max_steps + 1):
            try:
                batch = next(iterator)
            except StopIteration:
                iterator = iter(loader)
                batch = next(iterator)
            model.unet.train()
            optimizer.zero_grad(set_to_none=True)
            loss = _loss(model, scheduler, batch, device)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.unet.parameters(), 1.0)
            optimizer.step()
            if step % args.eval_every == 0 or step == args.max_steps:
                val = _validation(model, scheduler, val_data, device,
                                  args.val_samples, args.seed)
                record = {"step": step, "train_loss": round(loss.item(), 6),
                          "val_loss": round(val, 6)}
                if device.type == "cuda":
                    record["peak_gpu_reserved_gib"] = round(
                        torch.cuda.max_memory_reserved(device) / 1024**3, 3)
                log.write(json.dumps(record) + "\n")
                log.flush()
                print(json.dumps(record), flush=True)
                saved = {"unet": model.unet.state_dict(), "step": step,
                         "config": config, "val_loss": val}
                torch.save(saved, output / "latest.pt")
                if val < best_val:
                    best_val = val
                    torch.save(saved, output / "best.pt")


@torch.no_grad()
def sample(args):
    examples, digest, _ = load_examples(args.manifest, args.data_root)
    matching = [item for item in examples if item["row"]["split"] == args.split
                and item["row"]["character"] == args.character
                and item["row"]["target_style"] == args.style]
    if not matching:
        raise ValueError("指定字头/书体在该 split 中没有可用配对")
    item = matching[0]
    row = item["row"]
    ref = item["refs"][0]
    device = torch.device(args.device)
    finetuned = None
    if args.finetuned:
        saved = torch.load(args.finetuned, map_location="cpu")
        if saved["config"]["manifest_sha256"] != digest:
            raise ValueError("微调 checkpoint 与清单不匹配")
        finetuned = args.finetuned
    model, scheduler, upstream = load_model(args.ckpt_dir, device, finetuned)
    model.eval()
    dpm_model = upstream.FontDiffuserModelDPM(
        model.unet, model.style_encoder, model.content_encoder).to(device)
    pipeline = upstream.FontDiffuserDPMPipeline(
        dpm_model, scheduler, guidance_scale=args.guidance_scale)
    source = glyph_tensor(_path(args.data_root, row["source_image"]))
    reference = glyph_tensor(_path(args.data_root, ref["target_image"]))
    target = glyph_tensor(_path(args.data_root, row["target_image"]))
    torch.manual_seed(args.seed)
    generated = pipeline.generate(source.unsqueeze(0).to(device),
                                  reference.unsqueeze(0).to(device), batch_size=1,
                                  order=2, num_inference_step=args.steps,
                                  content_encoder_downsample_size=3, dm_size=(SIZE, SIZE))[0]
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (SIZE * 4, SIZE), "white")
    for index, image in enumerate((source, reference, target)):
        pixels = ((image + 1) * 127.5).byte().permute(1, 2, 0).numpy()
        canvas.paste(Image.fromarray(pixels), (index * SIZE, 0))
    canvas.paste(generated, (3 * SIZE, 0))
    canvas.save(args.output)
    metadata = {"character": args.character, "style": args.style, "font": item["font"],
                "split": args.split, "columns": ["source", "reference", "target", "generated"],
                "target_pair_id": row["pair_id"], "reference_pair_id": ref["pair_id"],
                "checkpoint": str(args.finetuned or args.ckpt_dir), "seed": args.seed,
                "steps": args.steps, "status": "generated_candidate_not_historical_evidence"}
    Path(args.output).with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(args.output)


def choose_prototype_comparison(examples, split, character, style,
                                target_pair_id=None, prototype_pair_id=None):
    """同字同书体、不同字库的真实图作结构原型；与目标不能同图。"""
    matches = [item for item in examples if item["row"]["split"] == split
               and item["row"]["character"] == character
               and item["row"]["target_style"] == style
               and (target_pair_id is None or item["row"]["pair_id"] == target_pair_id)]
    for target in matches:
        prototypes = [item for item in examples
                      if item["row"]["split"] == split
                      and item["row"]["character"] == character
                      and item["row"]["target_style"] == style
                      and item["font"] != target["font"]
                      and item["row"]["target_sha256"] != target["row"]["target_sha256"]
                      and (prototype_pair_id is None or item["row"]["pair_id"] == prototype_pair_id)]
        if prototypes:
            return target, prototypes[0]
    raise ValueError("没有同字同书体、不同字库且不同图片的结构原型")


@torch.no_grad()
def compare_prototype(args):
    examples, digest, _ = load_examples(args.manifest, args.data_root)
    target, prototype = choose_prototype_comparison(
        examples, args.split, args.character, args.style,
        args.target_pair_id, args.prototype_pair_id)
    reference_row = target["refs"][0]
    checkpoint = None
    if args.finetuned:
        saved = torch.load(args.finetuned, map_location="cpu")
        if saved["config"]["manifest_sha256"] != digest:
            raise ValueError("微调 checkpoint 与清单不匹配")
        checkpoint = args.finetuned
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    device = torch.device(args.device)
    model, scheduler, upstream = load_model(args.ckpt_dir, device, checkpoint)
    model.eval()
    dpm_model = upstream.FontDiffuserModelDPM(
        model.unet, model.style_encoder, model.content_encoder).to(device)
    pipeline = upstream.FontDiffuserDPMPipeline(
        dpm_model, scheduler, guidance_scale=args.guidance_scale)
    source = glyph_tensor(_path(args.data_root, target["row"]["source_image"]))
    prototype_image = glyph_tensor(_path(args.data_root, prototype["row"]["target_image"]))
    reference = glyph_tensor(_path(args.data_root, reference_row["target_image"]))
    actual_target = glyph_tensor(_path(args.data_root, target["row"]["target_image"]))
    generated = []
    for content in (source, prototype_image):
        torch.manual_seed(args.seed)
        image = pipeline.generate(content.unsqueeze(0).to(device),
                                  reference.unsqueeze(0).to(device), batch_size=1,
                                  order=2, num_inference_step=args.steps,
                                  content_encoder_downsample_size=3,
                                  dm_size=(SIZE, SIZE))[0]
        generated.append(image)
    canvas = Image.new("RGB", (SIZE * 6, SIZE), "white")
    for index, tensor in enumerate((source, prototype_image, reference, actual_target)):
        pixels = ((tensor + 1) * 127.5).byte().permute(1, 2, 0).numpy()
        canvas.paste(Image.fromarray(pixels), (index * SIZE, 0))
    canvas.paste(generated[0], (SIZE * 4, 0))
    canvas.paste(generated[1], (SIZE * 5, 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    metadata = {
        "character": args.character, "style": args.style, "split": args.split,
        "columns": ["modern_source", "target_stage_prototype", "style_reference",
                    "held_out_target", "generated_modern_content", "generated_prototype_content"],
        "target_pair_id": target["row"]["pair_id"], "target_font": target["font"],
        "prototype_pair_id": prototype["row"]["pair_id"], "prototype_font": prototype["font"],
        "reference_pair_id": reference_row["pair_id"],
        "target_sha256": target["row"]["target_sha256"],
        "prototype_sha256": prototype["row"]["target_sha256"],
        "checkpoint": str(checkpoint or args.ckpt_dir), "seed": args.seed,
        "steps": args.steps, "guidance_scale": args.guidance_scale,
        "oracle_assisted": True,
        "note": "原型取自同一 split 字头的真实目标书体图；本实验不检验未知古文字结构的推断能力。",
        "status": "generated_candidate_not_historical_evidence",
    }
    output.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description="FontDiffuser 官方权重的隔离微调实验")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("train", "sample", "compare-prototype"):
        sub = commands.add_parser(name)
        sub.add_argument("--manifest", type=Path, default=ROOT / "data/ml/style_pairs/manifest.jsonl")
        sub.add_argument("--data-root", type=Path, default=ROOT / "data")
        sub.add_argument("--ckpt-dir", type=Path,
                         default=ROOT / "data/ml/fontdiffuser/upstream/ckpt")
        sub.add_argument("--device", default="cuda:1")
        sub.add_argument("--seed", type=int, default=42)
        if name == "train":
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--batch-size", type=int, default=2)
            sub.add_argument("--max-steps", type=int, default=100)
            sub.add_argument("--eval-every", type=int, default=50)
            sub.add_argument("--val-samples", type=int, default=16)
            sub.add_argument("--learning-rate", type=float, default=1e-5)
            sub.add_argument("--content-mode", choices=("modern", "prototype"),
                             default="modern")
        else:
            sub.add_argument("--split", choices=("val", "test"), default="test")
            sub.add_argument("--character", required=True)
            sub.add_argument("--style", choices=("jiaguwen", "jinwen", "lishu", "xiaozhuan"),
                             required=True)
            sub.add_argument("--finetuned", type=Path)
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--steps", type=int, default=20)
            sub.add_argument("--guidance-scale", type=float, default=7.5)
            if name == "compare-prototype":
                sub.add_argument("--target-pair-id")
                sub.add_argument("--prototype-pair-id")
    args = parser.parse_args(argv)
    if args.command == "train":
        if min(args.batch_size, args.max_steps, args.eval_every, args.val_samples) < 1:
            parser.error("训练数量参数必须大于零")
        train(args)
    else:
        if args.steps < 1:
            parser.error("steps 必须大于零")
        if args.command == "sample":
            sample(args)
        else:
            compare_prototype(args)


if __name__ == "__main__":
    main()
