#!/usr/bin/env bash
# AgentCut 三端联调验证脚本
# 用法：在 Git Bash 中运行  bash verify.sh
# （不要用 PowerShell 跑，引号处理会坏）

echo "=== 1. Python 健康检查 ==="
curl -s http://127.0.0.1:8000/health

echo ""
echo "=== 2. Java 健康检查 ==="
curl -s http://127.0.0.1:8080/api/v1/health

echo ""
echo "=== 3. 建项目 ==="
PROJECT=$(curl -s -X POST http://127.0.0.1:8080/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"userId":0,"title":"verify"}')
echo "$PROJECT"

PROJECT_ID=$(echo "$PROJECT" | sed -n 's/.*"projectId":\([0-9]*\).*/\1/p')
echo "projectId = $PROJECT_ID"

echo ""
echo "=== 4. 存方案（含 speed 操作） ==="
curl -s -X PUT "http://127.0.0.1:8080/api/v1/plans/$PROJECT_ID" \
  -H "Content-Type: application/json" \
  -d '{"schemaVersion":"1.0","planVersion":1,"projectId":1,"title":"test","source":{"assetId":"a1","url":"fake.mp4","duration":60,"fps":30,"width":1920,"height":1080},"global":{"output":{"width":1080,"height":1920,"fps":30}},"timeline":[{"id":"seg_1","keep":true,"sourceRange":{"start":0,"end":10},"operations":[{"type":"speed","rate":1.5}]}]}'

echo ""
echo "=== 5. 查方案 + 版本 ==="
curl -s "http://127.0.0.1:8080/api/v1/plans/$PROJECT_ID"
echo ""
curl -s "http://127.0.0.1:8080/api/v1/plans/$PROJECT_ID/versions"

echo ""
echo "=== 6. Python 分析（模拟模式） ==="
curl -s -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"videoUrl":"fake.mp4","target":{"aspectRatio":"9:16","addSubtitle":true}}'

echo ""
echo "=== 完成 ==="
