# AidyCOS

AidyCOS es una capa modular para preparar instalaciones Linux existentes. El sistema base sigue siendo Debian, Arch, Ubuntu o Fedora; AidyCOS detecta la distribución y delega paquetes a un adaptador. No construye una ISO.

## Estado

Versión inicial de desarrollo: el primer destino es **Debian 13**. La detección reconoce las familias Debian, Arch y Fedora para orientar el diagnóstico, pero solo Debian 13 tiene un adaptador de instalación activo. Arch, Ubuntu y Fedora quedan preparados como destinos futuros.

El módulo `desktop-runtime` instala dependencias de sesión Wayland y multimedia presentes en el bootstrap Debian de Jugoo. No instala Jugoo ni Hyprland. Hyprland se deja fuera porque el bootstrap actual de Jugoo lo obtiene de backports, una decisión de repositorios que debe diseñarse por separado.

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

### Probar en otro Debian

Después de publicar el repositorio, el flujo en el segundo equipo será:

```sh
sudo apt install git python3 python3-venv
git clone https://github.com/<cuenta>/aidycos.git
cd aidycos
./scripts/install-local.sh
aidycos doctor
aidycos plan desktop-runtime
```

Para aplicar los paquetes del módulo:

```sh
aidycos install desktop-runtime --apply
```

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

El proyecto está estructurado para publicarse como un repositorio Git y distribuir el comando mediante PyPI o un paquete de distribución en una fase posterior. Para una instalación remota con un solo comando, primero conviene publicar una versión etiquetada y verificable; no se propone ejecutar un `curl | sh` desde la rama principal.
