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

## Aplicación de escritorio y notificaciones

En el PC de desarrollo (o una máquina ya instalada):

```bash
sudo ./scripts/instalar-aidylink.sh
```

Sin sudo (solo tu usuario): el wrapper queda en `~/.local/bin/aidylink` y el
acceso en `~/.local/share/applications/aidylink.desktop`.

El instalador de AidyCOS añade **AidyChat** al menú y al escritorio, con icono
propio. En QEMU / ISO: `sudo ./scripts/actualizar-qemu.sh` copia
`/opt/aidyc/aidylink`, `/usr/local/bin/aidylink` y el acceso. Atajo Hyprland:
**Super+C**.

Abrir: icono **AidyChat**, `aidylink ui`, o Super+C. La primera pantalla pide
solo el nombre visible del computador; después puedes elegir un equipo cercano
en una tarjeta o iniciar sesión con Google. El inicio de sesión ocurre en el
navegador del sistema y vuelve automáticamente a AidyLink.

La ventana puede cerrarse y el daemon continúa consultando mensajes y enviando
notificaciones del escritorio. Al pulsar **Abrir AidyChat** en una notificación,
se vuelve a abrir la ventana.

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
# Ventana gráfica: la primera apertura solicita solo el nombre del computador.
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
| `47832/udp` | Beacons de presencia (broadcast) |
| `47833/tcp` | Mensajes + hello de presencia (JSON lines + team HMAC) |

Si el Wi‑Fi bloquea broadcasts entre clientes, AidyLink también escanea la
subred por `47833/tcp` y hace un handshake `presence_hello` firmado.

## Conectar equipos de la red local

La ventana presenta los equipos compatibles en tarjetas; no es necesario
escribir IP o puerto. Para que se descubran entre sí, ambos deben usar el mismo
grupo y código local. Esa opción queda dentro de **Configuración avanzada de
red local** al crear la identidad.

## Usar con el servidor (AidyChat cloud)

Cuando el peer **no** está en la misma LAN, AidyLink enruta por AidyChat.

1. Cada persona inicia sesión con Google desde la ventana de AidyLink.
2. Para abrir un chat nuevo, usa **+** y busca a la persona por su nombre.

El mapeo de nombres a `user_id` queda disponible solo para el comando CLI
opcional `aidylink send`; el chat gráfico usa la lista de conversaciones de
AidyChat.

```bash
# Mapeo opcional para el comando aidylink send
aidylink cloud map Qemu 42
aidylink cloud map Host 17
systemctl --user restart aidylink
```

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
