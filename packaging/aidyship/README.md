# AidyShip

Commit y push rápido a GitHub para AidyCOS. Cada usuario conecta **su** cuenta con `gh`.

## Uso

```bash
aidyship ui          # ventana gráfica
aidyship status      # ¿hay sesión GitHub?
aidyship login       # abrir login en terminal + navegador
aidyship logout
aidyship repo .      # estado git
aidyship add-favorite /ruta/al/repo
aidyship publish -m "mensaje" [--deploy] [ruta]
aidyship deploy [ruta]   # solo PythonAnywhere (AidyC-web)
```

Atajo: `Super+G` (tras aplicar el perfil AidyCOS).

## Flujo

1. Abrir AidyShip → **Conectar GitHub**
2. Completar `gh auth login` en la terminal/navegador
3. Añadir repos favoritos
4. Marcar cambios → mensaje → **Commit** o **Commit + Push**
5. En **AidyC-web**: también **Publicar**, **Publicar + Deploy** y **Deploy** (mismo flujo que AidyCAI → SSH PythonAnywhere)

## Layout

| Ruta | Rol |
|------|-----|
| `/opt/aidyc/aidyship/` | Código |
| `/usr/local/bin/aidyship` | Wrapper |
| `~/.config/aidyship/config.json` | Favoritos |

## Dependencias

- `git`
- `gh` (GitHub CLI, paquete Debian)
- GTK 3 + PyGObject
