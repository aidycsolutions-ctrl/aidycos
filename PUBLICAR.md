# Publicar AidyCOS desde Antigravity

Esta carpeta es un repositorio Git local independiente. Para publicarlo usando la conexión de GitHub de Antigravity:

1. En Antigravity, abre la carpeta completa `outputs/AidyCOS`.
2. En el panel de control de versiones, confirma que aparece la rama `main` con el commit inicial.
3. Elige **Publish to GitHub** o **Publish Branch** y crea un repositorio nuevo llamado `aidycos` bajo `aidycsolutions-ctrl`.
4. Selecciona visibilidad **Public**. No uses el repositorio `AidyC-OS`: es privado y conserva el perfil anterior de ISO.
5. Confirma el `push` de la rama `main`.

El repositorio público ya es `https://github.com/aidycsolutions-ctrl/aidycos`. Después de publicar los últimos cambios en `main`, desde Debian 13 se instala el perfil con:

```sh
curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/install.sh | bash
```

Para revisar sin cambios antes de aplicar:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/aidycsolutions-ctrl/aidycos/main/install.sh) --dry-run
```

El instalador crea el entorno virtual del usuario, instala el perfil y configura los elementos del sistema definidos en README.md.
