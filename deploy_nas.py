"""把项目发布到局域网 NAS 的 Docker 容器。

凭据只从环境变量读取，不写进任何文件：
    NAS_HOST / NAS_USER / NAS_PASSWORD / NAS_DIR   全部必填
    SEED_DB=1                                      覆盖远端 data/lottery.db（默认只在远端没有时才写入）

用法：
    $env:NAS_HOST='nas.example'
    $env:NAS_USER='your-user'
    $env:NAS_PASSWORD='your-password'
    $env:NAS_DIR='/home/your-user/lottery-lab'
    python deploy_nas.py
"""

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent
UPLOAD = [
    "backend",
    "frontend",
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    ".dockerignore",
]
IGNORE_DIRS = {"__pycache__", "data", ".git"}
IGNORE_SUFFIX = {".pyc", ".pyo"}


def connect():
    host = os.environ.get("NAS_HOST")
    user = os.environ.get("NAS_USER")
    password = os.environ.get("NAS_PASSWORD")
    if not (host and user and password):
        sys.exit("请设置 NAS_HOST / NAS_USER / NAS_PASSWORD 环境变量")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=20)
    return client, host


def run(client, command: str) -> tuple[str, str]:
    stdin, stdout, stderr = client.exec_command(command, timeout=900)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    if stdout.channel.recv_exit_status() != 0:
        print(f"$ {command}\n{out}{err}")
        sys.exit(f"远端命令失败：{command}")
    return out, err


def upload(client, remote_dir: str) -> int:
    sftp = client.open_sftp()
    sent = 0
    try:
        for entry in UPLOAD:
            source = ROOT / entry
            if source.is_file():
                _put(sftp, source, f"{remote_dir}/{entry}")
                sent += 1
            else:
                sent += _put_tree(sftp, source, f"{remote_dir}/{entry}")
    finally:
        sftp.close()
    return sent


def _put_tree(sftp, local: Path, remote: str) -> int:
    try:
        sftp.mkdir(remote)
    except IOError:
        pass
    sent = 0
    for item in sorted(local.iterdir()):
        if item.is_dir():
            if item.name in IGNORE_DIRS:
                continue
            sent += _put_tree(sftp, item, f"{remote}/{item.name}")
        elif item.suffix not in IGNORE_SUFFIX:
            _put(sftp, item, f"{remote}/{item.name}")
            sent += 1
    return sent


def _put(sftp, local: Path, remote: str) -> None:
    sftp.put(str(local), remote)


def main() -> None:
    remote_dir = os.environ.get("NAS_DIR")
    if not remote_dir:
        sys.exit("请设置 NAS_DIR，例如 /home/your-user/lottery-lab")
    client, host = connect()
    try:
        run(client, f"mkdir -p {remote_dir}/data")
        print(f"上传到 {host}:{remote_dir}")
        print(f"  {upload(client, remote_dir)} 个文件")

        db = ROOT / "data" / "lottery.db"
        remote_db = f"{remote_dir}/data/lottery.db"
        seed = os.environ.get("SEED_DB") == "1"
        if not seed:
            out, _ = run(client, f"test -f {remote_db} && echo exists || echo missing")
            seed = "missing" in out
        if seed and db.exists():
            # 旧容器可能还开着这个库，先停掉并清掉 WAL，否则覆盖后会被 SQLite 判为损坏
            run(client, f"cd {remote_dir} && docker compose stop lottery-lab >/dev/null 2>&1 || true")
            run(client, f"rm -f {remote_db}-wal {remote_db}-shm {remote_db}-journal")
            sftp = client.open_sftp()
            try:
                sftp.put(str(db), remote_db)
            finally:
                sftp.close()
            print(f"  已写入开奖库 {db.stat().st_size // 1024} KB")
        else:
            print("  远端已有开奖库，保留 NAS 上的数据")

        print("构建并启动容器…")
        out, err = run(client, f"cd {remote_dir} && docker compose up -d --build 2>&1 | tail -20")
        print(out.strip() or err.strip())

        out, _ = run(client, f"cd {remote_dir} && docker compose ps --format '{{{{.Name}}}} {{{{.Status}}}} {{{{.Ports}}}}'")
        print(out.strip())
    finally:
        client.close()
    print(f"\n局域网地址：http://{host}:5179/")


if __name__ == "__main__":
    main()
