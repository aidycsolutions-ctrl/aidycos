# AidyCOS

AidyCOS adapta una instalación Linux existente al perfil de escritorio del proyecto, sin construir una ISO. El primer perfil automático es Debian 13; Arch, Ubuntu y Fedora están previstos en la arquitectura, pero todavía no tienen un instalador de perfil.

## Estado

La versión inicial prepara Debian 13 con Hyprland, SDDM, Wayland, NetworkManager, PipeWire, UPower, utilidades y Jugoo. La barra de Jugoo incluye los indicadores de Wi-Fi/red, volumen y batería (la batería se oculta cuando el equipo no tiene una); `Super+Space` abre el cajón de aplicaciones. El escritorio usa `swaybg` con el fondo AidyCOS (cambiable en **Configuración → Tema → Escritorio**), iconos que se crean o eliminan en **Accesos directos**, y la página **Atajos** para ver y gestionar atajos de teclado. En la barra hay un botón de cuadrícula que abre el cajón de aplicaciones (igual que `Super+Space`) y el dock de apps ancladas; puedes fijar o quitar apps desde el cajón. También instala AidyChat, una aplicación GTK nativa con acceso e icono en el escritorio, y asigna `Super+C` para abrirla. El perfil conserva los ajustes de GRUB y `cups-browsed` usados en AidyC-OS.

La instalación agrega fuentes oficiales de Debian solo cuando faltan paquetes esenciales, y usa `trixie-backports` para Hyprland. Selecciona SDDM como pantalla de acceso para que el usuario pueda iniciar Hyprland y Jugoo; guarda el nombre del gestor anterior en `/var/lib/aidycos/previous-display-manager`. Mantiene el usuario, la contraseña y el autologin existentes (no configura autologin). Hace una copia de la configuración Hyprland antes de añadir sus ajustes.

NumLock se activa en SDDM y en Hyprland. SDDM muestra el logo AidyCOS y un formulario de acceso personalizado; el teclado virtual de accesibilidad queda apagado por defecto. Hyprland queda como sesión para elegir en el primer inicio. Si se necesita el teclado virtual, se puede habilitar expresamente en `/etc/sddm.conf.d/99-aidycos.conf` cambiando `InputMethod=` por `InputMethod=qtvirtualkeyboard`. `aidylink init --name NOMBRE --team EQUIPO` configura el daemon de usuario para que mantenga las notificaciones activas con la ventana cerrada; al hacer clic en una notificación, se abre el chat. GRUB no muestra el menú durante el arranque normal y pasa opciones silenciosas al kernel; Plymouth muestra el logo AidyCOS sobre fondo negro. La pantalla del firmware BIOS/UEFI ocurre antes de GRUB y depende del fabricante.

Hyprland incluye botones de cerrar, maximizar y minimizar en las barras de título de las ventanas; doble clic en la barra maximiza o restaura. Firefox abre maximizado y `Alt+Tab`/`Alt+Shift+Tab` cambia entre ventanas. `Super+Alt+Flecha arriba` maximiza, `Super+Shift+Espacio` minimiza y `Ctrl+Alt+R` restaura la ventana minimizada; `Ctrl+Alt+G` organiza las ventanas en cuadrícula y `Ctrl+Alt+2/4` las divide en dos o cuatro espacios. `Ctrl+Alt+PageUp/PageDown` cambia de escritorio y, al añadir `Shift`, mueve la ventana. `Super+Flecha izquierda/derecha` cambia de escritorio; `Super+Y` y la flecha derecha abren el siguiente si aún no existe. `Ctrl+E` abre Thunar y `Imprimir` captura una región, la copia al portapapeles y pregunta si quieres guardar el archivo; el diálogo se cierra como “No guardar” si pierde el foco. Si hay una pantalla interna y otra externa conectadas, el inicio de sesión enfoca la externa y desactiva la interna para equipos cuyo panel integrado no funciona. En una instalación nueva, el dock incluye AidyC; al pulsar su icono se descarga e instala la versión Linux publicada si todavía no está instalada.

Al aplicar este perfil, se quita la versión anterior de AidyC si está instalada como paquete Debian; sus datos de usuario se conservan. Para quitarla de inmediato sin volver a aplicar el perfil, ejecuta `sudo apt remove aidyc`. El icono del dock abre AidyC si ya está instalada; para actualizarla, usa **Actualizar AidyC** en el menú de aplicaciones o ejecuta `aidyc-update`. El actualizador consulta el último release Linux publicado, compara la versión Debian instalada y pide confirmación antes de instalar una versión más nueva. No uses `purge` si quieres conservar los datos de la aplicación.

AidyCOS comprueba GitHub diariamente y muestra una ventana de confirmación cuando detecta un commit nuevo en `main`; solo descarga y reaplica el perfil si aceptas. También puedes iniciar la comprobación desde **Actualizar AidyCOS** en el menú o con `Super+Shift+U`. La actualización requiere conexión a Internet y pide la contraseña de administrador al aplicar los cambios.

El perfil replica la base funcional que se definió para la ISO, no los mecanismos propios de un sistema live. No instala live-boot, no crea usuarios temporales y no configura contraseñas. El equipo conserva su instalación Debian y los archivos personales. Antes de añadir atajos de Hyprland, el instalador guarda una copia de la configuración existente.

## Probar desde el checkout

Requiere Python 3.11 o posterior. Desde la raíz del repositorio:

```sh
python3 -m aidycos modules
python3 -m aidycos doctor
python3 -m aidycos plan desktop-runtime
```

`install` también es de solo lectura por defecto. Para ejecutar el plan en Debian 13, revisa primero los paquetes mostrados y luego confirma explícitamente:

```sh
python3 -m aidycos install desktop-runtime
python3 -m aidycos install desktop-runtime --apply
```

El modo `--apply` llama `apt-get update` y `apt-get install --no-install-recommends` con argumentos separados, usando `sudo` cuando no se ejecuta como root. La instalación de paquetes es repetible. AidyCOS no añade repositorios, no descarga scripts y no modifica archivos de configuración en esta versión.

Para instalar el comando de forma aislada en el usuario actual desde un checkout:

```sh
./scripts/install-local.sh
aidycos modules
```

El instalador crea un entorno virtual en `~/.local/share/aidycos/venv` y enlaza `aidycos` en `~/.local/bin`; no instala paquetes del sistema. Si Debian no tiene soporte de `venv`, el script indica el paquete requerido.

### Instalar el perfil con un comando

Después de publicar estos cambios en la rama `main`, en Debian 13 basta ejecutar:

```sh
curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/install.sh | bash
```

El instalador solicita `sudo` para paquetes y configuración del sistema. Se puede revisar la vista previa sin aplicar cambios:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/install.sh) --dry-run
```

Al completar correctamente, el equipo se reinicia automáticamente tras una cuenta regresiva de 15 segundos; pulsa `Ctrl+C` durante la cuenta para cancelarlo. Para posponer el reinicio, ejecuta:

```sh
curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/install.sh | bash -s -- --no-reboot
```

#### Usar el checkout de Jugoo en desarrollo

Para probar un checkout local de Jugoo, indica su ruta al aplicar el perfil:

```sh
AIDYCOS_JUGOO_SOURCE="$HOME/Documentos/Proyectos_AidyC/jugoo" \
  ./scripts/install-debian-profile.sh --no-reboot
```

La ruta se usa solo durante esa ejecución: se copia a un staging, se aplica el overlay y se instala en `/opt/aidyc/jugoo` sin modificar el checkout de desarrollo ni `~/.config/jugoo`. En el modo normal, cada actualización clona la rama `feature/atajos-aidyc-escritorio` de `aidycsolutions-ctrl/jugoo` (con fondo, atajos e iconos; si la rama no existe, usa `main`), aplica el overlay de AidyCOS y la instala en `/opt/aidyc/jugoo`. Puedes forzar otra ref con `AIDYCOS_JUGOO_REF`. Si ya existe una instalación de Jugoo no gestionada en esa ruta, se conserva como `/opt/aidyc/jugoo.aidycos-preserved` en la primera migración. Una selección guardada por versiones anteriores en `~/.config/aidycos/jugoo-source` se conserva como dato, pero ya no desvía futuras actualizaciones de la fuente oficial.

En SDDM elige **Hyprland** como sesión; normalmente quedará recordada para los siguientes inicios. Si las fuentes de APT del equipo están incompletas, AidyCOS agrega archivos dedicados y no reemplaza archivos de terceros.

El nombre `aidycos` y la ruta se deben ajustar si se publica con otro nombre. Primero ejecuta `plan` en esa máquina y revisa la lista antes de usar `--apply`.

## Añadir un módulo

Crea `aidycos/modules/<nombre>/module.toml`:

```toml
name = "mi-modulo"
description = "Descripción corta"
depends_on = ["desktop-runtime"]

[packages]
apt = ["paquete-debian"]
```

Los manifiestos solo contienen nombres de paquetes. El cargador valida el formato para evitar que un manifiesto convierta nombres de paquetes en argumentos de shell. Cada adaptador decide cómo mapear el módulo en su gestor.

## Diseño

```text
CLI → detección /etc/os-release → adaptador de paquetes
  └─ manifiestos TOML → resolución de dependencias → plan auditable → aplicación explícita
```

- `aidycos/distro.py`: parsea la identidad estándar de Linux y la familia.
- `aidycos/adapters/`: un adaptador por gestor (por ahora, APT para Debian 13).
- `modules/`: capacidades independientes declaradas en TOML.
- `aidycos/plan.py`: resuelve dependencias y deduplica paquetes antes de actuar.
- `tests/`: pruebas sin privilegios ni cambios en el sistema.

## Comandos iniciales

- `aidycos modules`: lista módulos disponibles.
- `aidycos doctor`: informa distribución y soporte.
- `aidycos plan <módulo...>`: muestra el plan sin cambios.
- `aidycos install <módulo...>`: muestra el plan; `--apply` lo ejecuta.

## Camino al repositorio público

El instalador de una línea descarga el archivo fuente público de la rama `main` y ejecuta el perfil. Para instalaciones administradas o repetibles en muchos equipos, el siguiente paso recomendado es publicar versiones etiquetadas y sumar verificación criptográfica.
