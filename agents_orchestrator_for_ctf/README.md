# CTF Multi-Agent Swarm

Оркестратор multi-agent системы для решения CTF тасков через CLIProxyAPI.

Базовый запуск:

```bash
python main.py --task-dir ./one_task --flag-format "CTF{...}"
```

MULTI режим:

```bash
python main.py \
  --mode multi \
  --ctfd-url https://ctf.example.com \
  --ctfd-token ctfd_abc123 \
  --flag-format "CTF{...}"
```
