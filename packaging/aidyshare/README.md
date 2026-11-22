# AidyShare

Cliente ligero de AidyCOS para **respaldar archivos en AidyCShare** del negocio
asociado al usuario AidyC. Puente temporal mientras se organiza AidyCloud.

## Idea

1. Login con usuario/contraseña AidyC (`/loginU2` → JWT).
2. Los archivos van a `uploads/sharecool/<padre_db>/` en el servidor (cuota **500 MB** por negocio).
3. Carpeta por defecto: `AidyCOS-Backup`.

No guarda la contraseña: solo el JWT en `~/.config/aidyshare/session.json` (modo 0600).

## Uso

```bash
aidyshare ui
aidyshare login --user USUARIO --password '…'
aidyshare status
aidyshare ls AidyCOS-Backup
aidyshare upload ~/Documento.pdf
aidyshare logout
```

## Layout

| Ruta | Rol |
|------|-----|
| `/opt/aidyc/aidyshare/` | Código (instalación de sistema) |
| `~/.local/share/aidyshare/` | Instalación de usuario |
| `~/.config/aidyshare/` | Config + sesión |
