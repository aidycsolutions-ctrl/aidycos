"""aidylink CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .cloud import apply_cloud_settings, test_cloud_connection
from .config import init_config, load_config, save_config
from .daemon import control_request, run_daemon
from .paths import config_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aidylink",
        description="Intercom LAN + relay AidyChat para AidyC-OS",
    )
    parser.add_argument("--version", action="version", version=f"aidylink {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Crear identidad local y secreto de equipo")
    p_init.add_argument("--name", required=True, help="Nombre visible (ej. Caja-1)")
    p_init.add_argument("--team", required=True, help="Id de equipo / tienda")
    p_init.add_argument(
        "--team-secret",
        default="",
        help="Secreto compartido (si omites, se genera; compártelo con el equipo)",
    )

    p_cloud = sub.add_parser("cloud", help="Configurar bridge AidyChat")
    cloud_sub = p_cloud.add_subparsers(dest="cloud_cmd", required=True)
    p_set = cloud_sub.add_parser("set", help="Guardar URL + Bearer token")
    p_set.add_argument("--base-url", required=True)
    p_set.add_argument("--token", required=True, help="Token aidychat_auth (Bearer)")
    p_set.add_argument("--poll", type=float, default=4.0)
    p_set.add_argument("--disable", action="store_true")
    p_map = cloud_sub.add_parser("map", help="Mapear nombre local → user_id AidyChat")
    p_map.add_argument("name")
    p_map.add_argument("user_id", type=int)
    cloud_sub.add_parser("show", help="Mostrar config cloud (token enmascarado)")
    cloud_sub.add_parser("test", help="Probar login Bearer contra el servidor")

    sub.add_parser("daemon", help="Correr daemon (discovery + LAN + cloud)")
    sub.add_parser("ui", help="Abrir ventana gráfica de chat")
    sub.add_parser("status", help="Estado del daemon")
    sub.add_parser("peers", help="Pares online en la LAN")

    p_send = sub.add_parser("send", help="Enviar texto (LAN preferido, cloud fallback)")
    p_send.add_argument(
        "to",
        nargs="?",
        default="",
        help="node_id, display_name, o nombre mapeado cloud (opcional con --host)",
    )
    p_send.add_argument("text", nargs="+", help="Mensaje")
    p_send.add_argument(
        "--host",
        default="",
        help="IP/host LAN directo (p.ej. 10.0.2.2 desde QEMU, o 127.0.0.1 con hostfwd)",
    )
    p_send.add_argument(
        "--port",
        type=int,
        default=0,
        help="Puerto TCP de mensajes (default: el de tu config, suele 47833)",
    )

    sub.add_parser("show-config", help="Mostrar config local (secretos enmascarados)")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        cfg = init_config(
            display_name=args.name,
            team_id=args.team,
            team_secret=args.team_secret or None,
        )
        print(f"OK · node_id={cfg.node_id}")
        print(f"    name={cfg.display_name} team={cfg.team_id}")
        print(f"    team_secret={cfg.team_secret}")
        print(f"    config={config_path()}")
        print("Comparte el mismo --team y --team-secret en todos los equipos del local.")
        return 0

    if args.cmd == "cloud":
        cfg = load_config()
        if cfg is None:
            print("Primero: aidylink init …", file=sys.stderr)
            return 1
        if args.cloud_cmd == "set":
            apply_cloud_settings(
                cfg,
                base_url=args.base_url,
                token=args.token,
                poll_seconds=args.poll,
                enabled=False if args.disable else None,
            )
            save_config(cfg)
            print(f"cloud enabled={cfg.cloud.enabled} base={cfg.cloud.base_url}")
            return 0
        if args.cloud_cmd == "map":
            cfg.cloud.peer_user_ids[args.name] = args.user_id
            save_config(cfg)
            print(f"map {args.name} → {args.user_id}")
            return 0
        if args.cloud_cmd == "show":
            token = cfg.cloud.bearer_token
            masked = (token[:4] + "…" + token[-4:]) if len(token) > 10 else ("***" if token else "")
            print(
                json.dumps(
                    {
                        "enabled": cfg.cloud.enabled,
                        "base_url": cfg.cloud.base_url,
                        "bearer_token": masked,
                        "poll_seconds": cfg.cloud.poll_seconds,
                        "peer_user_ids": cfg.cloud.peer_user_ids,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        if args.cloud_cmd == "test":
            try:
                result = test_cloud_connection(cfg)
            except Exception as exc:
                print(f"falló: {exc}", file=sys.stderr)
                return 1
            if result.get("ok"):
                save_config(cfg)
                print(
                    f"OK · user_id={result.get('user_id')} "
                    f"username={result.get('username')} "
                    f"base={result.get('base_url')}"
                )
                print("Reinicia el daemon: systemctl --user restart aidylink")
                return 0
            print(result.get("error") or "falló", file=sys.stderr)
            return 1

    if args.cmd == "daemon":
        asyncio.run(run_daemon())
        return 0

    if args.cmd == "ui":
        from .ui import run_ui

        return run_ui()

    if args.cmd == "show-config":
        cfg = load_config()
        if cfg is None:
            print("sin config", file=sys.stderr)
            return 1
        data = cfg.to_dict()
        secret = data.get("team_secret") or ""
        data["team_secret"] = (secret[:4] + "…") if len(secret) > 4 else "***"
        if data.get("cloud"):
            tok = data["cloud"].get("bearer_token") or ""
            data["cloud"]["bearer_token"] = (tok[:4] + "…") if len(tok) > 4 else ("***" if tok else "")
            turn = data["cloud"].get("turn_server") or ""
            if "@" in turn and "://" in turn:
                scheme, remainder = turn.split("://", 1)
                credentials, host = remainder.rsplit("@", 1)
                user = credentials.split(":", 1)[0]
                data["cloud"]["turn_server"] = f"{scheme}://{user}:***@{host}"
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    # Commands that talk to the daemon
    try:
        if args.cmd == "status":
            resp = control_request({"cmd": "status"})
        elif args.cmd == "peers":
            resp = control_request({"cmd": "peers"})
        elif args.cmd == "send":
            if not args.to and not args.host:
                print("Indica destinatario o --host", file=sys.stderr)
                return 2
            payload = {"cmd": "send", "to": args.to, "text": " ".join(args.text)}
            if args.host:
                payload["host"] = args.host
            if args.port:
                payload["port"] = args.port
            resp = control_request(payload)
        else:
            parser.error(f"comando desconocido: {args.cmd}")
            return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.cmd == "peers":
        peers = resp.get("peers") or []
        if not peers:
            print("(ningún peer online en la LAN)")
        for peer in peers:
            extra = ""
            if peer.get("aidychat_user_id"):
                extra = f" aidychat={peer['aidychat_user_id']}"
            print(
                f"{peer['display_name']}\t{peer['node_id'][:8]}…\t"
                f"{peer['host']}:{peer['message_port']}{extra}"
            )
        return 0 if resp.get("ok") else 1

    if args.cmd == "send":
        if resp.get("ok"):
            print(f"enviado via {resp.get('route')} → {resp.get('detail')}")
            return 0
        print(resp.get("detail") or resp.get("error") or "falló", file=sys.stderr)
        return 1

    print(json.dumps(resp, indent=2, ensure_ascii=False))
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
