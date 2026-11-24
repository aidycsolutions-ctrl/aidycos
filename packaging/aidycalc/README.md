# Calculadora

Calculadora de AidyCOS para el día a día y para cuentas un poco más largas.

- Aritmética con precedencia y paréntesis (`2+3*4`, `(2+3)*4`).
- Porcentaje de calculadora: `200+10%` = 220, `200-10%` = 180, `50%` = 0.5.
- Memoria (`MC`, `MR`, `M+`, `M−`), historial y repetición con `=`.
- Científicas en grados o radianes: `sin`, `cos`, `tan`, `ln`, `log`, `√`, `n!`, `π`.
- Acepta `.` y `,` como separador decimal. `mod(17;5)` y `log(100;10)` usan `;`.

Atajo: `Super+K`.

```bash
aidycalc
aidycalc eval '200+10%'
aidycalc eval 'sin(90)'
```
