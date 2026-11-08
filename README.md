# AidyCOS

AidyCOS adapta una instalación Linux existente al perfil de escritorio del proyecto, sin construir una ISO. El primer perfil automático es Debian 13; Arch, Ubuntu y Fedora están previstos en la arquitectura, pero todavía no tienen un instalador de perfil.

## Estado

La versión inicial prepara Debian 13 con el escritorio base del proyecto: Hyprland, SDDM, Wayland, audio, utilidades y Jugoo, además de los ajustes de GRUB y `cups-browsed` usados en el perfil de AidyC-OS.

La instalación agrega fuentes oficiales de Debian solo cuando faltan paquetes esenciales, y usa `trixie-backports` para Hyprland. Selecciona SDDM como pantalla de acceso para que el usuario pueda iniciar Hyprland y Jugoo; guarda el nombre del gestor anterior en `/var/lib/aidycos/previous-display-manager`. Mantiene el usuario, la contraseña y el autologin existentes (no configura autologin). Hace una copia de la configuración Hyprland antes de añadir sus ajustes.

NumLock se activa en la pantalla SDDM y en la sesión Hyprland. El perfil coloca el logo de `packaging/plymouth/AidyCOS.png` como fondo del menú GRUB y crea un tema Plymouth estático para la carga de Linux. El menú GRUB espera 2 segundos y la búsqueda de impresoras empieza después de llegar al entorno gráfico. La pantalla del firmware BIOS/UEFI ocurre antes de GRUB y depende del fabricante.

El perfil replica la base funcional que se definió para la ISO, no los mecanismos propios de un sistema live. No instala live-boot, no crea usuarios temporales y no configura contraseñas. El equipo conserva su instalación Debian y los archivos personales.

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

Al terminar, reinicia. En SDDM elige **Hyprland** como sesión; normalmente quedará recordada para los siguientes inicios. Si las fuentes de APT del equipo están incompletas, AidyCOS agrega archivos dedicados y no reemplaza archivos de terceros.

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
