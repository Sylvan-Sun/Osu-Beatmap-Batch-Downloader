#!/bin/bash
# ============================================================
# osu! 批量下图脚本
# BID（谱面编号）→ 自动解析 SID → 获取歌名 → 下载命名
# 镜像源: sayobot.cn
# ============================================================
# 用法:
#   ./osu_dl.sh bids.txt              # 默认输出到 ./osu_songs
#   ./osu_dl.sh bids.txt ./Songs      # 指定输出目录
#   ./osu_dl.sh bids.txt ./Songs mini # 下 mini 版（无视频）
#   ./osu_dl.sh -h                    # 查看帮助
# ============================================================

set -euo pipefail

# ---------- 帮助 ----------
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "用法: ./osu_dl.sh <bids.txt> [输出目录] [full|novideo|mini]"
    echo ""
    echo "bids.txt 格式 — 每行一个 BID（谱面编号），如:"
    echo "  724149"
    echo "  1092805"
    echo "  774837"
    echo ""
    echo "BID 从哪来 — osu.ppy.sh 谱面页 URL 中 /b/ 后面的数字"
    echo "  例: https://osu.ppy.sh/beatmapsets/123#osu/724149"
    echo "  → BID = 724149"
    echo ""
    echo "下载类型:"
    echo "  full    - 完整版（含视频），默认"
    echo "  novideo - 无视频版"
    echo "  mini    - 精简版（最小）"
    echo ""
    echo "文件名格式: BID Artist - Title.osz"
    exit 0
fi

# ---------- 参数 ----------
BID_FILE="${1:-bids.txt}"
OUTPUT_DIR="${2:-./osu_songs}"
TYPE="${3:-full}"

if [[ ! -f "$BID_FILE" ]]; then
    echo "[ERROR] 文件不存在: $BID_FILE"
    echo "用法: ./osu_dl.sh <bids.txt> [输出目录] [full|novideo|mini]"
    exit 1
fi

case "$TYPE" in full|novideo|mini) ;; *)
    echo "[ERROR] 下载类型只能是 full / novideo / mini"
    exit 1
esac

UA_DL="osu-downloader/1.0"
UA_WEB="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REFERER="https://osu.sayobot.cn/"

# ---------- 读取 & 去重 ----------
BIDS=()
declare -A SEEN
while IFS= read -r line; do
    line=$(echo "$line" | tr -d '[:space:]')
    if [[ "$line" =~ ^[0-9]+$ ]] && [[ -z "${SEEN[$line]:-}" ]]; then
        BIDS+=("$line")
        SEEN[$line]=1
    fi
done < "$BID_FILE"

TOTAL=${#BIDS[@]}
if [[ $TOTAL -eq 0 ]]; then
    echo "[ERROR] 没有有效 BID 在: $BID_FILE"
    exit 1
fi

RAW_LINES=$(grep -cE '^[0-9]+[[:space:]]*$' "$BID_FILE" 2>/dev/null || echo 0)
[[ $TOTAL -lt $RAW_LINES ]] && echo "[INFO] 输入 $RAW_LINES 行，去重 → $TOTAL 个"

mkdir -p "$OUTPUT_DIR"

echo "=============================================="
echo " osu! 批量下载"
echo "=============================================="
echo "输入:   $BID_FILE"
echo "数量:   $TOTAL 个谱面"
echo "输出:   $OUTPUT_DIR"
echo "类型:   $TYPE"
echo "命名:   BID Artist - Title.osz"
echo "=============================================="
echo ""

OK=0; FAILED=0; SKIP=0
FAIL_LIST=""

for i in "${!BIDS[@]}"; do
    BID="${BIDS[$i]}"
    PROGRESS="[$((i + 1))/$TOTAL]"

    # ---- 跳过已下载文件 ----
    EXISTING=$(ls "$OUTPUT_DIR/${BID}"*.osz 2>/dev/null | head -1) || true
    if [[ -n "$EXISTING" ]]; then
        echo "$PROGRESS BID $BID - 跳过 ($(basename "$EXISTING"))"
        ((SKIP++))
        continue
    fi

    # ---- Step 1: BID → SID ----
    printf "%s BID %s → 解析 SID ..." "$PROGRESS" "$BID"

    REDIR=$(curl -sI -o /dev/null -w "%{redirect_url}" \
        -H "User-Agent: $UA_WEB" \
        --connect-timeout 10 --max-time 15 \
        "https://osu.ppy.sh/b/$BID" 2>/dev/null)

    SID=$(echo "$REDIR" | sed -n 's|.*/beatmapsets/\([0-9]*\).*|\1|p')

    if [[ -z "$SID" ]]; then
        echo " 失败 (无法解析 SID，可能触发了限流)"
        FAIL_LIST+="  ${BID} → 解析失败"$'\n'
        ((FAILED++))
        sleep 3
        continue
    fi

    # ---- Step 2: 获取 Artist + Title ----
    INFO=$(curl -s "https://api.sayobot.cn/v2/beatmapinfo?0=$SID" \
        -H "User-Agent: $UA_WEB" \
        --connect-timeout 10 --max-time 15 2>/dev/null)

    ARTIST=$(echo "$INFO" | sed -n 's/.*"artist"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    TITLE=$(echo "$INFO" | sed -n 's/.*"title"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')

    if [[ -z "$ARTIST" || -z "$TITLE" ]]; then
        SAFE_NAME="${SID}"
        echo -n " [无元数据]"
    else
        RAW="${ARTIST} - ${TITLE}"
        SAFE_NAME=$(echo "$RAW" | sed 's|[\\/:*?"<>|]|_|g' | sed 's/[ .]*$//')
    fi

    OUTPUT="$OUTPUT_DIR/${BID} ${SAFE_NAME}.osz"

    # ---- Step 3: 下载 ----
    URL="https://dl.sayobot.cn/beatmaps/download/$TYPE/$SID"
    TMPFILE="$OUTPUT_DIR/_dl_${BID}.tmp"

    RESP=$(curl -L -o "$TMPFILE" \
        --connect-timeout 20 --max-time 180 \
        -H "User-Agent: $UA_DL" \
        -H "Referer: $REFERER" \
        -s -w "HTTP:%{http_code} SIZE:%{size_download}" \
        "$URL" 2>/dev/null)

    HTTP_CODE=$(echo "$RESP" | sed -n 's/.*HTTP:\([0-9]*\).*/\1/p')
    FSIZE=$(echo "$RESP" | sed -n 's/.*SIZE:\([0-9]*\).*/\1/p')

    if [[ "$HTTP_CODE" == "200" && "$FSIZE" -gt 1024 ]]; then
        KB=$((FSIZE / 1024))
        mv "$TMPFILE" "$OUTPUT"
        echo " 完成 (SID:$SID, ${KB}KB)"
        echo "    → $(basename "$OUTPUT")"
        ((OK++))
    elif [[ "$HTTP_CODE" == "404" || "$HTTP_CODE" == "403" ]]; then
        echo " 镜像未收录 (SID:$SID)"
        rm -f "$TMPFILE"
        FAIL_LIST+="  ${BID} → SID:${SID} (镜像未收录)"$'\n'
        ((FAILED++))
    else
        echo " 失败 (SID:$SID, HTTP:$HTTP_CODE)"
        rm -f "$TMPFILE"
        FAIL_LIST+="  ${BID} → SID:${SID} (HTTP ${HTTP_CODE})"$'\n'
        ((FAILED++))
    fi

    [[ $i -lt $((TOTAL - 1)) ]] && sleep 2
done

# ---------- 总结 ----------
echo ""
echo "=============================================="
echo " 下载完成"
echo "=============================================="
echo "成功:   $OK"
echo "跳过:   $SKIP (已存在)"
echo "失败:   $FAILED"
echo "总计:   $TOTAL"
echo "目录:   $(cd "$OUTPUT_DIR" && pwd)"
echo "大小:   $(du -sh "$OUTPUT_DIR" 2>/dev/null | cut -f1)"
if [[ -n "$FAIL_LIST" ]]; then
    echo "----------------------------------------------"
    echo "失败的 BID:"
    echo -n "$FAIL_LIST"
fi
echo "=============================================="
