# 持续集成

工作流：[CI](../.github/workflows/ci.yml)。GitHub 托管运行器统一使用 ubuntu-24.04。

## 自动检查

| 检查 | 环境 | 执行内容 |
|---|---|---|
| Python 3.11 / 3.14 | 固定版本的轻量测试依赖 | 全量 pytest、B1 共享样例、Schema/Java DTO/TypeScript 生成产物漂移、离线源索引/窗口/帧选择 |
| Java 17 | Temurin 17、Maven | 从后端根目录运行 verify，覆盖所有模块测试、编译和 jar 打包 |
| Frontend / Node 24 | Node 24、npm lockfile | npm ci、前端单测、跨端契约一致性、TypeScript 检查与 Vite 生产构建 |
| CI gate | 汇总以上三条任务线 | 仅在所有任务成功时成功；失败、取消、跳过均不能视为通过 |

所有 PR（含文档变更）、main 推送、合并队列及手动运行都会执行完整检查，不按路径跳过。
手动运行需要工作流先进入默认分支。相同 PR 或分支的新运行会取消旧运行；Python 矩阵中的单个失败不会取消其他版本。

## 测试边界

- CI 明确关闭 dotenv、强制模拟、清空模型凭证环境变量，无需仓库模型 Secrets。
- Python 使用 [requirements-test.txt](../AgentCut-ai/requirements-test.txt)，依赖精确锁定。
  Pydantic 版本与契约生成环境一致；pip check 检查依赖兼容。
- 测试环境不安装 OpenAI/LangChain、FunASR、PyAV/OpenCV 等可选运行库。模型/解码器路径通过替身验证。
- Java 测试仅使用进程内对象与本机随机端口 HTTP server，不启动 MySQL、Redis、消息队列或 Python 服务。
- 前端测试直接导入 TypeScript，使用 JSON import attributes 和 WebCrypto，因此统一要求 Node 24+。
  npm lockfile 使用官方注册表地址，并保留锁定版本与完整性校验。
- 此工作流不代表真实 ASR/VLM、真实视频质量、浏览器交互或应用渲染已经通过验收。

## 报告和构建产物

Python JUnit XML 与 Java Surefire XML 在测试失败时也尝试上传；前端构建成功后上传 dist。
产物保留七天，名称含运行次数，避免重新运行时重名。仅上传明确路径，不上传运行工作目录或配置。
CI gate 会在运行摘要中列出各任务结果，详细失败日志在对应任务中查看。

## 合并检查

在 GitHub 仓库的 branch rules/rulesets 中，可将稳定名称 **CI gate** 设为 main 的 required status check。
工作流本身产生检查结果；阻止失败 PR 合并需要仓库规则配合。当前变更不修改仓库权限或分支规则。
若启用 merge queue，本工作流已响应 merge_group。

第三方 Actions 固定为完整提交 SHA，并注明 release 版本：
[checkout](https://github.com/actions/checkout/releases/tag/v7.0.1)、
[setup-python](https://github.com/actions/setup-python/releases/tag/v7.0.0)、
[setup-java](https://github.com/actions/setup-java/releases/tag/v6.1.0)、
[setup-node](https://github.com/actions/setup-node/releases/tag/v7.1.0)、
[upload-artifact](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)。
后续升级应同时核对官方 release 和 SHA，再通过本工作流验证。
工作流使用只读 contents 权限，checkout 不保留 Git 凭证。

## 本地复现

Python：从仓库根目录创建独立测试虚拟环境，避免把开发模型依赖混入测试基线。

```sh
python3.11 -m venv /tmp/agentcut-ci-python
/tmp/agentcut-ci-python/bin/python -m pip install -r AgentCut-ai/requirements-test.txt
/tmp/agentcut-ci-python/bin/python -m pip check
cd AgentCut-ai
AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_VLM_API_KEY='' AGENTCUT_LLM_API_KEY='' \
  /tmp/agentcut-ci-python/bin/python -m pytest -q --junitxml=reports/pytest.xml
```

也可用 Python 3.14 执行同一组命令。Windows 可使用独立虚拟环境的 Scripts/python.exe。

Java：使用 Java 17，从仓库根目录执行。

```sh
cd AgentCut-backend
mvn --batch-mode --no-transfer-progress verify
```

前端：使用 Node 24+，从仓库根目录执行。npm ci 会重建当前目录下的 node_modules。

```sh
cd AgentCut-front
npm ci --no-audit --no-fund
npm test
npm run test:contracts
npm run build
```

修改契约后若漂移检查失败，先检查权威 Python 模型，再运行 scripts/generate_b1_contracts.py
和 scripts/generate_b1_fixtures.py 更新全部生成文件；三端共享样例必须仍然通过。
