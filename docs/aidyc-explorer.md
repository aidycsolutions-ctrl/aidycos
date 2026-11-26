# AidyC Explorer

La integración de AidyCOS con Nemo añade la acción **Cambiar etiqueta de la USB…** al menú de Nemo. El explorador que aparece en el menú y se abre con `Super+E` es **AidyCExplorer**; esta integración no añade un segundo lanzador. Se incluye en el perfil AidyCOS para Debian 13 y utiliza el escritorio que ya esté instalado.

## Alcance de esta integración

- `nemo`: exploración de carpetas, vistas de iconos o lista, pestañas y operaciones habituales como copiar, mover, renombrar y eliminar archivos. Debian lo instala junto con `gvfs`.
- `udisks2`: detección, montaje y desmontaje de unidades extraíbles y API para cambiar la etiqueta de un sistema de archivos sin formatearlo.
- `dosfstools`, `exfatprogs`, `ntfs-3g`: herramientas que UDisks2 usa para etiquetas FAT, exFAT y NTFS.
- `libglib2.0-bin` y `zenity`: llamada D-Bus a UDisks2 y diálogo gráfico para pedir y confirmar la nueva etiqueta.

La disposición de Nemo ofrece panel lateral de ubicaciones, barra de navegación y vistas de archivos, un patrón familiar para usuarios de Windows. El módulo no instala Cinnamon ni un entorno de escritorio completo. Algunas bibliotecas y datos compartidos de Cinnamon aparecen como dependencias propias de Nemo; no son el shell ni el escritorio Cinnamon.

## Instalación controlada

Revisa primero los paquetes que APT resolverá en el equipo destino:

```sh
aidycos plan aidyc-explorer
```

Si el plan es adecuado, instala explícitamente:

```sh
aidycos install aidyc-explorer --apply
```

AidyCOS usa `--no-install-recommends`, por eso las herramientas de etiquetas se declaran directamente. Se omite `gvfs-backends`, que amplía el soporte para protocolos remotos y no hace falta para USB local. No añade repositorios ni cambia asociaciones de archivos, tema, paneles, inicio automático o gestor predeterminado.

El perfil de AidyCOS integra el lanzador y la acción de forma reversible en el usuario del equipo. Para instalar solo el módulo en un Debian 13 que ya tenga la CLI, inspecciona primero el plan:

```sh
./scripts/install-aidyc-explorer.sh
```

El instalador copia, solo para el usuario actual, la acción personalizada de Nemo, su ayudante y el icono. No instala lanzador propio: si queda el duplicado **AidyC Explorer** de una versión anterior, lo retira. Para abrir archivos usa **AidyCExplorer** (`Super+E`) y, para la etiqueta USB, abre Nemo. Si Nemo ya estaba abierto, ciérralo y vuelve a iniciarlo para cargar la acción.

Conecta y abre la USB. Haz clic derecho sobre un archivo o carpeta que esté dentro de la memoria y elige **Cambiar etiqueta de la USB…**. La acción pregunta el nuevo nombre, pide confirmación, desmonta sin forzar, cambia solo la etiqueta con UDisks2 y vuelve a montar la unidad. Si hay archivos o ventanas abiertas que impiden desmontar, cancela la operación y cierra esos archivos; la acción no fuerza el desmontaje.

La acción admite particiones USB FAT, exFAT y NTFS. El propio controlador del sistema de archivos valida los caracteres y la longitud de la etiqueta. Discos internos, discos completos, otros formatos y dispositivos que no se identifiquen como USB quedan rechazados. La API de UDisks2 muestra autenticación del sistema cuando sea necesaria.

## Reversión

Para retirar el lanzador, icono y acción del usuario, desde el checkout ejecuta:

```sh
./scripts/uninstall-aidyc-explorer.sh
```

El desinstalador conserva archivos de integración que hayas editado. Nemo y sus paquetes del sistema quedan instalados. Para retirar solo Nemo, revisa primero la simulación y confirma cualquier retirada en APT:

```sh
sudo apt-get -s remove nemo
sudo apt-get remove nemo
```

UDisks2 o GVfs pueden estar siendo usados por otros componentes del sistema; no los retires a ciegas. Si deseas evaluar dependencias que queden sin uso, inspecciona `sudo apt-get -s autoremove` antes de ejecutar cualquier eliminación. No uses `purge` para esta reversión.

## Límites y evolución

La acción se muestra en el menú de Nemo al seleccionar un archivo de una partición USB. Nemo 6.4 de Debian 13 no admite todavía acciones en el menú contextual del dispositivo en el panel lateral, por eso se usa el menú del contenido de la memoria. AidyC Explorer conserva las preferencias visuales de Nemo; la vista y el tamaño de iconos siguen bajo control del usuario.

La lista APT está pensada para Debian 13, el destino soportado actualmente por AidyCOS. Antes de ampliar soporte a otras distribuciones, se debe revisar el nombre y disponibilidad de estos paquetes en cada adaptador.
