# MCP-RDC

Self-hosted управление удалённым компьютером для ChatGPT и Codex через MCP.

Архитектура специально сделана максимально простой:

~~~text
ChatGPT -> HTTPS/MCP -> VPS gateway <- WSS/TLS <- Windows-агент
~~~

Без SSH-сервера на Windows. Без WinRM. Без публичных портов на Windows. Агент сам держит
исходящее защищённое WebSocket-соединение с VPS.

MCP-RDC не зависит от того, где и как у вас поднят WireGuard: на хосте, в Docker или его нет вообще.

## Что входит в v0.1

- Официальный MCP Python SDK v2 и Streamable HTTP
- Постоянно работающий Windows-агент с автоматическим переподключением
- Доступ к файловой системе только в разрешённых каталогах
- Чтение, запись, просмотр каталогов и tail файлов
- Выполнение PowerShell-команд
- Просмотр процессов
- Получение статуса, запуск и остановка Windows Scheduled Tasks
- Получение Git HEAD и статуса рабочей директории
- Статус агента и системные метаданные
- MCP-аннотации для read/write/destructive операций
- Ограничение размера вывода и маскирование токена агента
- systemd-инсталлятор для Linux gateway
- Инсталлятор Windows-агента через Scheduled Task
- CI для Linux и Windows
- CD на VPS после успешного CI

## Сетевая схема

Gateway по умолчанию слушает только localhost на VPS:

~~~text
127.0.0.1:8765
~~~

Reverse proxy, например Caddy, публикует два отдельных TLS-маршрута:

~~~text
https://mcp.example.com/<mcp-secret>/mcp
wss://mcp.example.com/<agent-secret>/agent/v1/connect
~~~

MCP URL используется ChatGPT/Codex. Второй URL используется только Windows-агентом и
дополнительно защищён отдельным bearer token.

Подробнее: `docs/ARCHITECTURE.md`.

## Быстрая установка

### 1. VPS

Клонируйте репозиторий на VPS и запустите:

~~~bash
sudo bash ./scripts/install-vps.sh --domain mcp.example.com
~~~

Инсталлятор:

- создаёт Python virtual environment;
- устанавливает MCP-RDC;
- генерирует отдельные секретные пути для MCP и Windows-агента;
- генерирует bearer token агента;
- устанавливает systemd unit;
- запускает gateway только на localhost;
- проверяет `/healthz`;
- выводит точный MCP URL, agent WSS URL и Caddy-конфигурацию.

### 2. Reverse proxy

На чистом VPS можно передать `--manage-caddy`: инсталлятор сам установит Caddy, создаст конфиг и включит TLS.

Если Caddy уже был установлен с чужой конфигурацией, инсталлятор откажется её перезаписывать.

Шаблон ручной конфигурации находится в `deploy/Caddyfile.example`.

### 3. Windows / octarin

В локальном клоне репозитория запустите PowerShell от имени администратора:

~~~powershell
.\scripts\install-windows.ps1 -GatewayWs "wss://mcp.example.com/<agent-secret>/agent/v1/connect" -AgentToken "<token>" -AgentId "octarin" -AllowedRoots "C:\hh-agent"
~~~

Инсталлятор создаёт каталог `C:\ProgramData\MCP-RDC`, защищает конфигурацию агента
и регистрирует `MCP-RDC Agent` как SYSTEM Scheduled Task, которая запускается при старте Windows
и автоматически перезапускается при сбое.

### 4. ChatGPT

Включите Developer Mode и добавьте MCP URL, который вывел VPS-инсталлятор:

~~~text
https://mcp.example.com/<mcp-secret>/mcp
~~~

Для приватного single-user deployment high-entropy MCP path используется как секрет доступа.
Не публикуйте его. OAuth 2.1 можно добавить следующим уровнем защиты, если MCP-RDC станет
многопользовательским или публичным.

## Continuous Deployment

После первичной настройки VPS gateway может обновляться автоматически после каждого успешного CI в `main`.

CD не требует GitHub-токена для доступа VPS к репозиторию. GitHub Actions архивирует ровно тот
commit, который прошёл CI, подключается к VPS по SSH с паролем из GitHub Secret, загружает архив,
запускает `install-vps.sh --manage-caddy --quiet`, поднимает/обновляет Caddy, перезапускает systemd service и проверяет `/healthz`.

Workflow находится в `.github/workflows/cd.yml`.

Для включения CD один раз настройте GitHub Environment `production`.

Secrets:

- `MCP_RDC_VPS_HOST` - публичный IP или DNS-имя VPS
- `MCP_RDC_VPS_USER` - SSH-пользователь: root либо пользователь с passwordless sudo
- `MCP_RDC_VPS_PASSWORD` - пароль SSH-пользователя
- `MCP_RDC_VPS_KNOWN_HOSTS` - необязательно; строка known_hosts. Если не задана, workflow использует `ssh-keyscan`

Variables:

- `MCP_RDC_CD_ENABLED=true` - включает автоматический deploy
- `MCP_RDC_DOMAIN=mcp.example.com` - публичный домен MCP
- `MCP_RDC_VPS_SSH_PORT=22` - SSH-порт

Пока `MCP_RDC_CD_ENABLED` не равен `true`, CD workflow безопасно пропускает deploy.

На VPS релизы сохраняются в `/opt/mcp-rdc/releases/<commit-sha>`, а
`/opt/mcp-rdc/current-source` указывает на текущий release. Хранятся последние пять релизов.

## Модель безопасности

Файловые инструменты могут работать только внутри настроенных разрешённых каталогов.

`run_powershell` намеренно обладает расширенными правами и может выйти за пределы файловых
ограничений. Поэтому в MCP metadata он помечен как destructive и non-idempotent.

Контур управления включает:

- TLS на публичном reverse proxy
- отдельный high-entropy MCP path
- отдельный high-entropy agent path
- отдельный high-entropy bearer token для Windows-агента
- gateway слушает только localhost
- отсутствие входящих MCP-RDC портов на Windows

## Разработка

~~~bash
python -m venv .venv
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
~~~

## Лицензия

MIT
