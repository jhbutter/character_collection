#!/usr/bin/env bash
# 在 screen 内运行有界续采；默认参数是历史 53 字到 60 字批次。
set -u -o pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 2

TARGET="${1:-60}"
START_ID="${2:-70}"
END_ID="${3:-110}"
MAX_ROUNDS="${4:-5}"

for value in "$TARGET" "$START_ID" "$END_ID" "$MAX_ROUNDS"; do
    if [[ ! "$value" =~ ^[0-9]+$ ]]; then
        echo "参数必须为正整数" >&2
        exit 2
    fi
done
if (( TARGET < 54 || TARGET > 100 || START_ID < 1 || END_ID < START_ID || END_ID - START_ID >= 100 || MAX_ROUNDS < 1 || MAX_ROUNDS > 10 )); then
    echo "参数超出范围：target 54–100；编号跨度至多100；轮数1–10" >&2
    exit 2
fi

BATCH="expand_${TARGET}_screen"
FOLDER="$PROJECT_ROOT/data/batches/$BATCH"
OUTPUT="$PROJECT_ROOT/data/dataset_${TARGET}_screen"
mkdir -p "$FOLDER"
exec > >(tee -a "$FOLDER/run.log") 2>&1

echo "[$(date -Is)] 开始 $BATCH，编号 $START_ID–$END_ID，最多 $MAX_ROUNDS 轮；含金文"
for (( round = 1; round <= MAX_ROUNDS; round++ )); do
    echo "[$(date -Is)] 第 $round 轮，每轮最多100张新图"
    if "$PROJECT_ROOT/.venv/bin/python" -m hanzi_evolution.cli collect-expand \
        --execute --new-only --start-id "$START_ID" --end-id "$END_ID" \
        --target "$TARGET" --max-images 100 --interval 7 \
        --folder "$FOLDER" --output "$OUTPUT"; then
        command_status=0
    else
        command_status=$?
    fi

    if [[ ! -f "$FOLDER/status.json" ]]; then
        echo "缺少批次状态文件，停止（命令退出码 $command_status）" >&2
        exit 2
    fi
    read -r state failed_sources count downloaded < <(
        "$PROJECT_ROOT/.venv/bin/python" -c \
            'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); print(d["status"],sum(r["status"]=="failed" for r in d["cross_records"]),d["character_count"],d["downloaded_this_run"])' \
            "$FOLDER/status.json"
    )
    echo "[$(date -Is)] 状态=$state，字头=$count，本轮下载=$downloaded，来源失败=$failed_sources"
    if (( failed_sources > 0 )); then
        echo "有跨来源失败记录，停止并等待检查，不把不完整批次视为完成" >&2
        exit 2
    fi
    if [[ "$state" == "budget_reached" ]]; then
        if (( downloaded == 0 )); then
            echo "图片预算停止但本轮无新增下载，停止以避免空转" >&2
            exit 2
        fi
        echo "本轮达到图片预算，继续下一轮；已有图片按缓存复用"
        continue
    fi
    if [[ "$state" == "finished" && "$command_status" -eq 0 ]]; then
        echo "[$(date -Is)] 已完成；报告 reports/$BATCH.json；目录 $OUTPUT"
        exit 0
    fi
    echo "状态 $state：停止，不自动重试访问受限、解析失败或字头不足" >&2
    exit 2
done

echo "达到 $MAX_ROUNDS 轮上限，停止；可检查状态后用同一命令续跑" >&2
exit 2
