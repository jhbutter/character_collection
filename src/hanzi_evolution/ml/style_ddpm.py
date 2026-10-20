"""64×64 楷书图到指定书体的条件 DDPM 实验。运行时才需要 ml 可选依赖。"""

import argparse
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from diffusers import DDIMScheduler, DDPMScheduler, UNet2DModel
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from hanzi_evolution.ml.pairs import CORE_TARGETS

SIZE = 64
PREPROCESS_VERSION = "alpha-bbox-white-v1"
DEFAULT_STYLES = tuple(CORE_TARGETS)


def image_tensor(path, size=SIZE):
    """以 alpha 为笔画掩码，黑字白底、等比居中，返回 [-1, 1] 灰度图。"""
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    alpha = image.getchannel("A")
    box = alpha.getbbox()
    if box is None:
        raise ValueError(f"空白字形图：{path}")
    alpha = alpha.crop(box)
    width, height = alpha.size
    scale = (size - 8) / max(width, height)
    resized = alpha.resize((max(1, round(width * scale)), max(1, round(height * scale))),
                           Image.Resampling.LANCZOS)
    canvas = Image.new("L", (size, size), 255)
    ink = Image.new("L", resized.size, 0)
    canvas.paste(ink, ((size - resized.width) // 2, (size - resized.height) // 2), resized)
    values = np.asarray(canvas, dtype=np.float32).copy() / 127.5 - 1.0
    return torch.from_numpy(values).unsqueeze(0)


def _image_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"图片路径超出 data 根目录：{relative}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_manifest(manifest, data_root, styles=DEFAULT_STYLES):
    manifest = Path(manifest)
    styles = tuple(styles)
    if not styles or len(styles) != len(set(styles)):
        raise ValueError("styles 必须是非空且不重复的书体列表")
    content = manifest.read_bytes()
    rows = [json.loads(line) for line in content.splitlines() if line.strip()]
    rows = [row for row in rows if row["target_style"] in styles]
    if not rows:
        raise ValueError("清单中没有指定书体的配对")
    by_character = {}
    checked_images = set()
    for row in rows:
        split = row["split"]
        if split not in {"train", "val", "test"}:
            raise ValueError(f"未知 split：{split}")
        character = row["character"]
        previous = by_character.setdefault(character, split)
        if previous != split:
            raise ValueError(f"字头跨 split：{character}")
        for key in ("source_image", "target_image"):
            path = _image_path(data_root, row[key])
            expected = row.get(key.replace("_image", "_sha256"))
            if expected and path not in checked_images:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != expected:
                    raise ValueError(f"原图 SHA-256 不匹配：{path}")
                checked_images.add(path)
    if not any(row["split"] == "train" for row in rows):
        raise ValueError("清单缺少 train 配对")
    return rows, hashlib.sha256(content).hexdigest()


class PairDataset(Dataset):
    def __init__(self, rows, data_root, split, styles):
        self.rows = [row for row in rows if row["split"] == split]
        self.data_root = Path(data_root)
        self.style_ids = {style: index for index, style in enumerate(styles)}

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        return {
            "source": image_tensor(_image_path(self.data_root, row["source_image"])),
            "target": image_tensor(_image_path(self.data_root, row["target_image"])),
            "style_id": self.style_ids[row["target_style"]],
        }


def make_model(styles=DEFAULT_STYLES, channels=(64, 128, 192, 256)):
    """2 通道输入：加噪目标 + 干净楷书；1 通道输出：预测目标噪声。"""
    if len(channels) != 4 or any(channel % 32 for channel in channels):
        raise ValueError("channels 需要四个 32 的倍数")
    return UNet2DModel(
        sample_size=SIZE,
        in_channels=2,
        out_channels=1,
        layers_per_block=2,
        block_out_channels=tuple(channels),
        down_block_types=("DownBlock2D", "DownBlock2D", "AttnDownBlock2D", "AttnDownBlock2D"),
        up_block_types=("AttnUpBlock2D", "AttnUpBlock2D", "UpBlock2D", "UpBlock2D"),
        num_class_embeds=len(styles),
    )


def _denoise_loss(model, scheduler, batch, device, generator=None):
    source = batch["source"].to(device)
    target = batch["target"].to(device)
    style_ids = batch["style_id"].to(device)
    noise = torch.randn(target.shape, device=device, generator=generator)
    timesteps = torch.randint(scheduler.config.num_train_timesteps, (len(target),),
                              device=device, generator=generator)
    noisy = scheduler.add_noise(target, noise, timesteps)
    predicted = model(torch.cat((noisy, source), dim=1), timesteps,
                      class_labels=style_ids).sample
    return F.mse_loss(predicted, noise)


def _validate(model, scheduler, loader, device, seed):
    if loader is None:
        return None
    model.eval()
    generator = torch.Generator(device=device).manual_seed(seed)
    losses = []
    with torch.no_grad():
        for batch in loader:
            losses.append(_denoise_loss(model, scheduler, batch, device, generator).item())
    model.train()
    return sum(losses) / len(losses)



@torch.no_grad()
def _sample_tensor(model, source, style_id, scheduler, generator):
    sample = torch.randn(source.shape, device=source.device, generator=generator)
    for timestep in scheduler.timesteps:
        predicted = model(torch.cat((sample, source), dim=1), timestep,
                          class_labels=style_id).sample
        sample = scheduler.step(predicted, timestep, sample).prev_sample
    return ((sample[0, 0].clamp(-1, 1) + 1) * 127.5).byte().cpu().numpy()


def _preview(model, val_data, styles, device, output, step, seed):
    if not val_data:
        return
    was_training = model.training
    model.eval()
    scheduler = DDIMScheduler(num_train_timesteps=1000, beta_schedule="squaredcos_cap_v2",
                              prediction_type="epsilon", clip_sample=True)
    scheduler.set_timesteps(20, device=device)
    selected = {}
    for index, row in enumerate(val_data.rows):
        selected.setdefault(row["target_style"], index)
    canvas = Image.new("L", (SIZE * 3, SIZE * len(selected)), 255)
    labels = []
    for line, style in enumerate(style for style in styles if style in selected):
        index = selected[style]
        row = val_data.rows[index]
        item = val_data[index]
        source = item["source"].unsqueeze(0).to(device)
        style_id = torch.tensor([item["style_id"]], device=device)
        generator = torch.Generator(device=device).manual_seed(seed + line)
        generated = _sample_tensor(model, source, style_id, scheduler, generator)
        source_pixels = ((item["source"][0] + 1) * 127.5).byte().numpy()
        target_pixels = ((item["target"][0] + 1) * 127.5).byte().numpy()
        for column, pixels in enumerate((source_pixels, generated, target_pixels)):
            canvas.paste(Image.fromarray(pixels), (SIZE * column, SIZE * line))
        labels.append({"row": line, "character": row["character"], "style": style})
    preview_dir = output / "previews"
    preview_dir.mkdir(exist_ok=True)
    canvas.save(preview_dir / f"step_{step:06d}.png")
    (preview_dir / "layout.json").write_text(json.dumps({
        "columns": ["source", "generated", "target"], "rows": labels,
        "split": "val", "seed": seed,
    }, ensure_ascii=False, indent=2) + "\n")
    model.train(was_training)


def _save_checkpoint(path, model, optimizer, step, config, best_val):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                "step": step, "config": config, "best_val": best_val}, temporary)
    temporary.replace(path)


def train(args):
    rows, digest = load_manifest(args.manifest, args.data_root, args.styles)
    train_data = PairDataset(rows, args.data_root, "train", args.styles)
    val_data = PairDataset(rows, args.data_root, "val", args.styles)
    if args.max_steps < 1 or args.batch_size < 1 or args.eval_every < 1:
        raise ValueError("max-steps、batch-size、eval-every 必须大于零")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用；请先检查 NVIDIA 设备和 PyTorch CUDA 版本")
    device = torch.device(args.device)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    model = make_model(args.styles, args.channels).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    scheduler = DDPMScheduler(num_train_timesteps=1000, beta_schedule="squaredcos_cap_v2",
                              prediction_type="epsilon")
    config = {"styles": list(args.styles), "channels": list(args.channels), "size": SIZE,
              "preprocess": PREPROCESS_VERSION, "manifest_sha256": digest,
              "seed": args.seed, "learning_rate": args.learning_rate}
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    config_path = output / "config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("输出目录的配置或清单已变化，请使用新的 output 目录")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    start_step, best_val = 0, float("inf")
    latest = output / "latest.pt"
    if latest.exists():
        saved = torch.load(latest, map_location="cpu", weights_only=True)
        if saved["config"] != config:
            raise ValueError("checkpoint 配置与当前训练不一致")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        start_step, best_val = saved["step"], saved["best_val"]
    if start_step >= args.max_steps:
        print(f"已完成 {start_step} 步")
        return
    train_loader = DataLoader(train_data, batch_size=args.batch_size, shuffle=True,
                              drop_last=False, num_workers=args.num_workers)
    val_loader = (DataLoader(val_data, batch_size=args.batch_size, shuffle=False,
                             num_workers=args.num_workers) if val_data else None)
    iterator = iter(train_loader)
    model.train()
    with (output / "metrics.jsonl").open("a", encoding="utf-8") as log:
        for step in range(start_step + 1, args.max_steps + 1):
            try:
                batch = next(iterator)
            except StopIteration:
                iterator = iter(train_loader)
                batch = next(iterator)
            optimizer.zero_grad(set_to_none=True)
            loss = _denoise_loss(model, scheduler, batch, device)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            if step % args.eval_every == 0 or step == args.max_steps:
                val_loss = _validate(model, scheduler, val_loader, device, args.seed)
                metrics = {"step": step, "train_loss": round(loss.item(), 6),
                           "val_loss": round(val_loss, 6) if val_loss is not None else None}
                if device.type == "cuda":
                    metrics["peak_gpu_reserved_gib"] = round(
                        torch.cuda.max_memory_reserved(device) / 1024**3, 3)
                log.write(json.dumps(metrics) + "\n")
                log.flush()
                print(json.dumps(metrics), flush=True)
                if val_loss is not None and val_loss < best_val:
                    best_val = val_loss
                    _save_checkpoint(output / "best.pt", model, optimizer, step, config, best_val)
                _save_checkpoint(latest, model, optimizer, step, config, best_val)
                _preview(model, val_data, args.styles, device, output, step, args.seed)


@torch.no_grad()
def generate(args):
    saved = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = saved["config"]
    if config["size"] != SIZE or config["preprocess"] != PREPROCESS_VERSION:
        raise ValueError("checkpoint 的预处理版本不匹配")
    if args.style not in config["styles"]:
        raise ValueError(f"不支持书体 {args.style}；可用：{', '.join(config['styles'])}")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用")
    device = torch.device(args.device)
    model = make_model(config["styles"], config["channels"]).to(device)
    model.load_state_dict(saved["model"])
    model.eval()
    source = image_tensor(args.source).unsqueeze(0).to(device)
    style_id = torch.tensor([config["styles"].index(args.style)], device=device)
    scheduler = DDIMScheduler(num_train_timesteps=1000, beta_schedule="squaredcos_cap_v2",
                              prediction_type="epsilon", clip_sample=True)
    scheduler.set_timesteps(args.steps, device=device)
    generator = torch.Generator(device=device).manual_seed(args.seed)
    images = []
    for _ in range(args.count):
        pixels = _sample_tensor(model, source, style_id, scheduler, generator)
        images.append(Image.fromarray(pixels))
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"不会覆盖已有输出：{output}")
    output.mkdir(parents=True)
    for index, image in enumerate(images, 1):
        image.save(output / f"candidate_{index:02d}.png")
    (output / "metadata.json").write_text(json.dumps({
        "source": str(args.source), "style": args.style, "seed": args.seed,
        "steps": args.steps, "checkpoint": str(args.checkpoint),
        "training_step": saved["step"], "manifest_sha256": config["manifest_sha256"],
        "status": "generated_candidate_not_historical_evidence",
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"已生成 {len(images)} 张候选图：{output}")



@torch.no_grad()
def evaluate(args):
    """对一个完整的留出 split 逐字逐书体生成可人工检查的对照图。"""
    saved = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = saved["config"]
    rows, digest = load_manifest(args.manifest, args.data_root, config["styles"])
    if digest != config["manifest_sha256"]:
        raise ValueError("评估清单与训练 checkpoint 不一致")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用")
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"不会覆盖已有输出：{output}")
    selected = {}
    for row in rows:
        if row["split"] == args.split:
            selected.setdefault(row["character"], {}).setdefault(row["target_style"], row)
    if not selected:
        raise ValueError(f"清单中没有 {args.split} 配对")
    device = torch.device(args.device)
    model = make_model(config["styles"], config["channels"]).to(device)
    model.load_state_dict(saved["model"])
    model.eval()
    scheduler = DDIMScheduler(num_train_timesteps=1000, beta_schedule="squaredcos_cap_v2",
                              prediction_type="epsilon", clip_sample=True)
    scheduler.set_timesteps(args.steps, device=device)
    output.mkdir(parents=True)
    index = []
    for character, by_style in sorted(selected.items()):
        styles = [style for style in config["styles"] if style in by_style]
        canvas = Image.new("L", (SIZE * 3, SIZE * len(styles)), 255)
        labels = []
        for line, style in enumerate(styles):
            row = by_style[style]
            source = image_tensor(_image_path(args.data_root, row["source_image"]))
            target = image_tensor(_image_path(args.data_root, row["target_image"]))
            generator = torch.Generator(device=device).manual_seed(args.seed + len(index) * 10 + line)
            style_id = torch.tensor([config["styles"].index(style)], device=device)
            generated = _sample_tensor(model, source.unsqueeze(0).to(device),
                                       style_id, scheduler, generator)
            source_pixels = ((source[0] + 1) * 127.5).byte().numpy()
            target_pixels = ((target[0] + 1) * 127.5).byte().numpy()
            for column, pixels in enumerate((source_pixels, generated, target_pixels)):
                canvas.paste(Image.fromarray(pixels), (SIZE * column, SIZE * line))
            labels.append({"row": line, "style": style, "target_pair_id": row["pair_id"]})
        canvas.save(output / f"{character}.png")
        index.append({"character": character, "rows": labels})
    (output / "metadata.json").write_text(json.dumps({
        "split": args.split, "columns": ["source", "generated", "target"],
        "characters": index, "seed": args.seed, "steps": args.steps,
        "checkpoint": str(args.checkpoint), "training_step": saved["step"],
        "manifest_sha256": digest, "status": "generated_candidate_not_historical_evidence",
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"已评估 {len(index)} 个 {args.split} 字头：{output}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="64×64 条件 DDPM 书体候选图实验")
    commands = parser.add_subparsers(dest="command", required=True)
    train_parser = commands.add_parser("train")
    train_parser.add_argument("--manifest", type=Path, default=Path("data/ml/style_pairs/manifest.jsonl"))
    train_parser.add_argument("--data-root", type=Path, default=Path("data"))
    train_parser.add_argument("--output", type=Path, default=Path("data/ml/style_ddpm/run_001"))
    train_parser.add_argument("--styles", nargs="+", default=list(DEFAULT_STYLES), choices=DEFAULT_STYLES)
    train_parser.add_argument("--channels", nargs=4, type=int, default=[64, 128, 192, 256])
    train_parser.add_argument("--batch-size", type=int, default=16)
    train_parser.add_argument("--max-steps", type=int, default=10000)
    train_parser.add_argument("--eval-every", type=int, default=500)
    train_parser.add_argument("--learning-rate", type=float, default=1e-4)
    train_parser.add_argument("--seed", type=int, default=20261019)
    train_parser.add_argument("--num-workers", type=int, default=2)
    train_parser.add_argument("--device", default="cuda:0")
    sample_parser = commands.add_parser("sample")
    sample_parser.add_argument("--checkpoint", type=Path, required=True)
    sample_parser.add_argument("--source", type=Path, required=True)
    sample_parser.add_argument("--style", required=True, choices=DEFAULT_STYLES)
    sample_parser.add_argument("--output", type=Path, required=True)
    sample_parser.add_argument("--count", type=int, default=4)
    sample_parser.add_argument("--steps", type=int, default=50)
    sample_parser.add_argument("--seed", type=int, default=42)
    sample_parser.add_argument("--device", default="cuda:0")
    eval_parser = commands.add_parser("evaluate")
    eval_parser.add_argument("--checkpoint", type=Path, required=True)
    eval_parser.add_argument("--manifest", type=Path, default=Path("data/ml/style_pairs/manifest.jsonl"))
    eval_parser.add_argument("--data-root", type=Path, default=Path("data"))
    eval_parser.add_argument("--split", choices=("val", "test"), default="test")
    eval_parser.add_argument("--output", type=Path, required=True)
    eval_parser.add_argument("--steps", type=int, default=50)
    eval_parser.add_argument("--seed", type=int, default=42)
    eval_parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args(argv)
    if args.command == "train":
        train(args)
    elif args.command == "sample":
        if args.count < 1 or args.steps < 1:
            parser.error("count、steps 必须大于零")
        generate(args)
    else:
        if args.steps < 1:
            parser.error("steps 必须大于零")
        evaluate(args)


if __name__ == "__main__":
    main()
