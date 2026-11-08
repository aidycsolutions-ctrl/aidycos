# AidyLink

Comunicación interna entre máquinas AidyC-OS: **LAN primero**, AidyChat como **relay cloud**.

## Modelo

```
Misma red                         Fuera de LAN
─────────────────────             ──────────────────────
UDP discovery + TCP JSON     →    AidyChat REST (Bearer)
Notificaciones Jugoo/FDO          polling new-messages
```

Cada equipo corre un daemon de usuario. Los pares se anuncian en la LAN;
si el destinatario no está online localmente y hay token AidyChat, el
mensaje se enruta por la API `/aidychat`.

## Instalar como aplicación (menú + comando)

En el PC de desarrollo (o una máquina ya instalada):

```bash
sudo ./scripts/instalar-aidylink.sh
```

Sin sudo (solo tu usuario): el wrapper queda en `~/.local/bin/aidylink` y el
acceso en `~/.local/share/applications/aidylink.desktop`.

En QEMU / ISO: `sudo ./scripts/actualizar-qemu.sh` copia `/opt/aidyc/aidylink`,
`/usr/local/bin/aidylink` y el `.desktop` del menú. Atajo Hyprland: **Super+C**.

Abrir: menú «AidyLink», `aidylink ui`, o Super+C. La UI arranca el daemon sola.

Con una cuenta AidyChat vinculada, `aidylink ui` abre la nueva ventana nativa
GTK: conversaciones a la izquierda, mensajes, búsqueda, adjuntos e imágenes en
el chat, grabación de notas de voz, llamadas de voz/vídeo y botón de
intercomunicador (mantener pulsado para hablar). Los adjuntos usan el límite
del servidor AidyChat (50 MB).

Las llamadas usan WebRTC de GStreamer con ICE/STUN. Si la red bloquea la
conexión directa, configura un relay TURN desde el botón de cuenta de la
ventana. El servidor debe proporcionar credenciales TURN válidas. Para voz y
vídeo, AidyC-OS instala los componentes GStreamer junto con la imagen.

## Uso rápido

```bash
# Primera vez: identidad + equipo
aidylink init --name "Caja-1" --team "mi-tienda"

# Vincular AidyChat (token Bearer de una sesión web/login)
aidylink cloud set --base-url https://angeljoc.pythonanywhere.com \
  --token "<aidychat_auth Bearer>"

# Daemon en segundo plano (también: systemctl --user enable --now aidylink)
aidylink daemon &
# o: systemctl --user start aidylink

# Ventana gráfica (también en el menú de aplicaciones: «AidyLink»)
aidylink ui

# CLI opcional
aidylink peers
aidylink send <peer-id|nombre> "¿Libre en caja?"
```

## Layout

| Ruta | Rol |
|------|-----|
| `/opt/aidyc/aidylink/` | Código |
| `~/.config/aidylink/config.json` | Identidad, team key, cloud |
| `~/.local/share/aidylink/` | Estado / inbox local |
| `/run/user/$UID/aidylink.sock` | Control socket CLI ↔ daemon |

## Puertos LAN

| Puerto | Protocolo |
|--------|-----------|
| `47832/udp` | Beacons de presencia |
| `47833/tcp` | Mensajes (JSON lines + team HMAC) |

## Usar con el servidor (AidyChat cloud)

Cuando el peer **no** está en la misma LAN, AidyLink enruta por AidyChat.

1. Cada persona tiene cuenta en AidyChat (`https://www.aidycsolutions.com/aidychat/`).
2. En cada PC, vincula el token:

```bash
# Token = cookie aidychat_auth (DevTools → Application → Cookies)
# o el campo "token" del JSON de login (tras desplegar el cambio en AidyC-web)
aidylink cloud set \
  --base-url https://www.aidycsolutions.com \
  --token "PEGAR_TOKEN_AQUI"
aidylink cloud test
```

3. Mapea el nombre local del compañero → su `user_id` numérico de AidyChat:

```bash
aidylink cloud map Qemu 42          # en el Host
aidylink cloud map Host 17          # en la VM / otra PC
systemctl --user restart aidylink
```

También desde la UI: botón **Servidor…**.

Orden de envío: **LAN si el peer está online** → si no, **cloud** con el mapeo.

## Probar host real ↔ QEMU

Con `probar-qemu.sh` (NAT + `hostfwd`):

| Dirección | Comando |
|-----------|---------|
| VM → host | En la VM: `aidylink send --host 10.0.2.2 "hola host"` |
| Host → VM | En el host: `aidylink send --host 127.0.0.1 --port 47834 "hola vm"` |

1. Cierra QEMU → `sudo ./scripts/actualizar-qemu.sh` (copia `/opt/aidyc/aidylink`)
2. Host: mismo `--team` / `--team-secret` que la VM → `aidylink daemon`
3. `./probar-qemu.sh` → en la VM `aidylink init …` + `aidylink daemon`
4. Prueba los dos envíos de la tabla (el discovery UDP **no** lista peers cruzando NAT)

## Alcance actual

- Chat local LAN existente y enlace con AidyChat para conversaciones remotas.
- Interfaz GTK nativa estilo mensajería, lista de chats, búsqueda y envío de
  texto, imágenes, audio, vídeo y documentos mediante AidyChat.
- Grabación de notas de voz con PipeWire y reproducción con el reproductor
  predeterminado del escritorio.
- Llamadas WebRTC de audio y vídeo con señalización de AidyChat; el
  intercomunicador mantiene el micrófono silenciado hasta que se mantiene
  pulsado el botón.
