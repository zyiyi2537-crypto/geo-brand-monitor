#!/usr/bin/env bash
# Vigilath GEO skill 一行安装 —— 给对方 agent(小龙虾)drop-in。
#
#   curl -fsSL https://geo.vigilath.com/skill/install.sh | bash -s -- <你的token>
#
# 干三件事:① 把 skill 拷进探测到的 skills 目录;② token 写进 ~/.vigilath/config(chmod 600);③ 自检。
# 不挑框架:自动探测常见 skills 目录,也可用 --dir / 环境变量 VIGILATH_SKILLS_DIR 指定。
set -euo pipefail

SKILL_BASE="${VIGILATH_SKILL_BASE:-https://geo.vigilath.com/skill}"   # skill 文件托管地址
TOKEN=""
SKILLS_DIR="${VIGILATH_SKILLS_DIR:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) SKILLS_DIR="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    -*) echo "未知参数:$1" >&2; exit 2 ;;
    *) [ -z "$TOKEN" ] && TOKEN="$1"; shift ;;
  esac
done

say() { printf '\033[36m[vigilath-geo]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[vigilath-geo] 错误:%s\033[0m\n' "$*" >&2; exit 1; }

[ -n "$TOKEN" ] || die "缺少 token。用法:install.sh <你的token>(在 Vigilath 控制台「集成」页一键获取)"
command -v python3 >/dev/null 2>&1 || die "需要 python3(skill 客户端纯标准库,无三方依赖)"

# ① 探测 skills 目录:--dir / 环境变量 > Claude > 当前项目 ./skills > 兜底 ~/.vigilath/skills
if [ -z "$SKILLS_DIR" ]; then
  if [ -d "$HOME/.claude/skills" ]; then SKILLS_DIR="$HOME/.claude/skills"
  elif [ -d "./skills" ]; then SKILLS_DIR="$(pwd)/skills"
  else SKILLS_DIR="$HOME/.vigilath/skills"; fi
fi
DEST="$SKILLS_DIR/vigilath-geo"
mkdir -p "$DEST/scripts"
say "安装到:$DEST"

# 拷贝 skill 文件:本地仓库直跑则用本地,否则从托管地址下载
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
fetch() { # fetch <相对路径> <目标>
  if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/$1" ]; then cp "$SELF_DIR/$1" "$2"
  else curl -fsSL "$SKILL_BASE/$1" -o "$2"; fi
}
fetch "SKILL.md" "$DEST/SKILL.md"
fetch "README.md" "$DEST/README.md"
fetch "scripts/geo_client.py" "$DEST/scripts/geo_client.py"

# ② token + API 基址写配置(API 基址从下载 skill 的同一 host 推出,自动对齐 test/prod)
mkdir -p "$HOME/.vigilath"
umask 077
API_BASE="${SKILL_BASE%/skill}/api/agent/v1"
{
  echo "# Vigilath GEO —— 机密,勿提交"
  echo "VIGILATH_AGENT_TOKEN=$TOKEN"
  echo "VIGILATH_BASE=$API_BASE"
} > "$HOME/.vigilath/config"
chmod 600 "$HOME/.vigilath/config"
say "token + API 基址($API_BASE)已写入 ~/.vigilath/config(权限 600)"

# ③ 自检
say "自检中…"
if python3 "$DEST/scripts/geo_client.py" capabilities >/dev/null 2>&1; then
  say "✅ 安装完成,链路已通。试试:python3 $DEST/scripts/geo_client.py chat \"我被搜到几个问题?\""
else
  printf '\033[33m[vigilath-geo] 已安装,但自检未通(token 失效?网络?)。手动验证:\033[0m\n'
  echo "  python3 $DEST/scripts/geo_client.py capabilities"
fi
