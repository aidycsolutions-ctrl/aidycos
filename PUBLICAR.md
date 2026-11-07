# Publicar AidyCOS desde Antigravity

Esta carpeta es un repositorio Git local independiente. Para publicarlo usando la conexión de GitHub de Antigravity:

1. En Antigravity, abre la carpeta completa `outputs/AidyCOS`.
2. En el panel de control de versiones, confirma que aparece la rama `main` con el commit inicial.
3. Elige **Publish to GitHub** o **Publish Branch** y crea un repositorio nuevo llamado `aidycos` bajo `aidycsolutions-ctrl`.
4. Selecciona visibilidad **Public**. No uses el repositorio `AidyC-OS`: es privado y conserva el perfil anterior de ISO.
5. Confirma el `push` de la rama `main`.

Cuando termine, el repositorio será `https://github.com/aidycsolutions-ctrl/aidycos`. Desde el Debian de prueba:

```sh
sudo apt install git python3 python3-venv
git clone https://github.com/aidycsolutions-ctrl/aidycos.git
cd aidycos
./scripts/install-local.sh
aidycos doctor
aidycos plan desktop-runtime
```

La instalación de paquetes del sistema queda como paso separado y explícito:

```sh
aidycos install desktop-runtime --apply
```

El script crea un entorno virtual del usuario. No requiere ejecutar scripts descargados con `curl | sh`.
