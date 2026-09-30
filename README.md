# MCP-RDC

Self-hosted управление удалённым компьютером для ChatGPT и Codex через MCP.

Архитектура специально сделана максимально простой:

~~~text
ChatGPT -> HTTPS / MCP -> Linux VPS -> WireGuard -> Windows-агент 
~~~

Без SSH-сервера на Windows. Без WinRM. Без публичных портов на Windows. Агент на Windows держит
исходящее WebSocket-соединение с VPS через уже существующую сеть WireGuard.

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

## Сетевая схема

Gateway слушает WireGuard IP VPS, а не публичный интерфейс.

Reverse proxy, например Caddy, публикует только:

~~~text
https://mcp.example.com/<high-entropy-secret>/mcp
~~~

Windows-агент подключается к gateway напрямую через WireGuard:

~~~text
ws://<VPS-WG-IP>:8765/agent/v1/connect
~~~

Публичный reverse proxy не должен проксировать `/agent/v1/connect`.

Подробнее: `docs/ARCHITECTURE.md`.

## Быстрая установка

### 1. VPS

Клонируйте репозиторий на VPS и запустите:

~~~bash
sudo bash ./scripts/install-vps.sh --domain mcp.example.com --wg-interface wg0
~~~

Инсталлятор:

- определяет WireGuard IP VPS;
- создаёт Python virtual environment;
- устанавливает MCP-RDC;
- генерирует оба секрета;
- устанавливает systemd unit;
- запускает gateway;
- выводит точный публичный MCP URL и параметры для установки Windows-агента.

Инсталлятор специально не изменяет существующую конфигурацию reverse proxy автоматически.

### 2. Reverse proxy

Добавьте Caddy-конфигурацию, которую выведет инсталлятор, и перезагрузите Caddy.

Шаблон находится в `deploy/Caddyfile.example`.

### 3. Windows / octarin

В локальном клоне репозитория запустите PowerShell от имени администратора:

~~~powershell
.\scripts\install-windows.ps1 -GatewayWs "ws://10.0.0.1:8765/agent/v1/connect" -AgentToken "<token>" -AgentId "octarin" -AllowedRoots "C:\hh-agent"
~~~

Инсталлятор создаёт каталог `C:\ProgramData\MCP-RDC`, защищает конфигурацию агента
и регистрирует `MCP-RDC Agent` как SYSTEM Scheduled Task, которая запускается при старте Windows
и автоматически перезапускается при сбое.

### 4. ChatGPT

Включите Developer Mode и добавьте MCP URL, который вывел VPS-инсталлятор:

~~~text
https://mcp.example.com/<secret>/mcp
~~~

Для приватного single-user deployment этот high-entropy endpoint используется как секрет доступа.
Не публикуйте его. OAuth 2.1 можно добавить следующим уровнем защиты, если MCP-RDC станет
многопользовательским или публичным.

## Continuous Deployment

После первичной настройки VPS gateway может обновляться автоматически после каждого успешного CI в `main`.

CD не требует GitHub-токена или deploy key для доступа VPS к репозиторию. GitHub Actions
архивирует ровно тот commit, который прошёл CI, подключается к VPS по SSH с паролем из GitHub Secret, загружает архив и запускает
`install-vps.sh --quiet`, перезапускает systemd service и проверяет `/healthz`.

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
- `MCP_RDC_WG_INTERFACE=wg0` - WireGuard-интерфейс VPS
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
- high-entropy, практически неугадываемый MCP path
- WireGuard между VPS и Windows
- отдельный high-entropy bearer token для агента
- отсутствие публичного маршрута к Windows-агенту
- отсутствие слушающих MCP-RDC сервисов на публичном или LAN-интерфейсе Windows

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
