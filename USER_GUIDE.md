# open-refinery — Deployment Guide

From a fresh VPS to a running, logged-in instance. Assumes a Linux VPS (Ubuntu/
Debian shown); adapt package commands for other distros.

---

## 1. Prerequisites

open-refinery needs **Python 3.11+**. SQLite ships with Python — there is no
separate database to install or run.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 --version   # confirm >= 3.11
```

---

## 2. Install

Install into a virtual environment (keeps it isolated from system Python):

```bash
python3 -m venv ~/open-refinery-venv
source ~/open-refinery-venv/bin/activate
pip install open-refinery
open-refinery --help
```

`pipx install open-refinery` also works if you prefer a managed global CLI.

---

## 3. Environment variables

Only **`SECRET_KEY`** is required — it signs session tokens and encrypts stored
service credentials. Generate a strong one:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put your configuration in an env file (e.g. `~/open-refinery.env`):

```bash
# required
SECRET_KEY=<paste the generated value>

# optional (sensible defaults shown)
# PORT=8000
# DATABASE_URL=sqlite:////var/lib/open-refinery/open-refinery.db
# LOG_LEVEL=INFO

# optional — enable "Sign in with GitHub" and OAuth service connections
# GITHUB_CLIENT_ID=...
# GITHUB_CLIENT_SECRET=...
# GITLAB_CLIENT_ID=...
# GITLAB_CLIENT_SECRET=...
# APP_BASE_URL=https://refinery.example.com   # your public URL (for OAuth callbacks)
```

Keep this file private (`chmod 600 ~/open-refinery.env`) and **never commit it**.
By default the database is a file in the working directory; set `DATABASE_URL`
to an absolute path you control (and back it up — it holds all your data).

---

## 4. Create the first admin

Load the env and create the admin account from the CLI (you can also do this
in the browser via the first-run setup wizard — see step 6):

```bash
set -a; . ~/open-refinery.env; set +a
open-refinery create-admin --email you@example.com
# prompts for a password, prints a token — you log in with the email + password
```

---

## 5. Run the server in the background

Pick a port (see the Ports section below), then start it detached. Simplest:

```bash
set -a; . ~/open-refinery.env; set +a
nohup open-refinery serve --port 8000 > ~/open-refinery.log 2>&1 &
```

- `nohup … &` keeps it running after you log out; output goes to the log file.
- `tmux` or `screen` are good alternatives if you want an attachable session.
- Check it: `curl http://localhost:8000/health` → `{"status":"ok"}`.
- Stop it: `pkill -f "open-refinery serve"`.

---

## 6. Log in

Open your server's URL in a browser (e.g. `http://YOUR_SERVER_IP:8000`).

- On a **fresh instance** the dashboard shows a setup wizard — create the admin
  there if you skipped step 4.
- Otherwise sign in with the admin **email + password**.

From the dashboard you manage everything: users, repositories, processes,
integrations, oversight, and the audit trail.

---

## Ports

- **Default is 8000.** Fine while you're evaluating: browse to `:8000`.
- **Port 80 to start (plain HTTP).** For a friendlier `http://your-host` with no
  port in the URL, run on **80**. Ports below 1024 are privileged, so either:
  ```bash
  # grant the python binary permission to bind low ports (preferred)
  sudo setcap 'cap_net_bind_service=+ep' $(readlink -f ~/open-refinery-venv/bin/python3)
  open-refinery serve --port 80
  ```
  Running the whole server as root just to bind 80 is **not** recommended.

## Going public: use HTTPS on 443

**For any public-facing VPS, serve over HTTPS on 443 with a valid TLS
certificate.** Don't expose plain HTTP — tokens and credentials would travel
unencrypted. The clean pattern is a **reverse proxy** that terminates TLS and
forwards to open-refinery on a local port (e.g. 8000).

**Caddy** (automatic Let's Encrypt certificates — easiest):

```
# /etc/caddy/Caddyfile
refinery.example.com {
    reverse_proxy localhost:8000
}
```
Point your domain's DNS at the VPS, `sudo systemctl reload caddy`, and Caddy
obtains and renews the certificate automatically on 443.

**nginx + certbot** is the equivalent if you already run nginx: proxy_pass to
`http://localhost:8000` and use `certbot --nginx` for the certificate.

When behind a proxy on a domain, set **`APP_BASE_URL=https://refinery.example.com`**
so OAuth callback URLs are built correctly, and keep open-refinery bound to
`localhost:8000` (not the public interface).

## Hardening checklist

- Firewall: allow 443 (and 80 for cert challenges) publicly; keep 8000 local only.
- `SECRET_KEY`: strong, secret, and stable — changing it invalidates sessions
  and makes stored service credentials undecryptable.
- Back up the SQLite database file regularly.
- Keep the OS and `open-refinery` updated (`pip install -U open-refinery`, then
  restart the server).
