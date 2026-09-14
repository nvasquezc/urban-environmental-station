# Guía de contribución

## Ramas

- `main`: solo versiones etiquetadas y publicadas.
- `develop`: integración.
- `feature/*`, `fix/*`, `docs/*`: trabajo puntual, sale de `develop`.

## Commits

Formato [Conventional Commits](https://www.conventionalcommits.org/es/):

```
feat(firmware): agregar frontend I2S para MEMS
fix(analysis): corregir pareo horario con intervalos incompletos
docs(calibracion): precisar criterio de partición temporal
```

Ámbitos: `firmware`, `analysis`, `hardware`, `docs`, `ci`.

## Antes de abrir un PR

- El firmware compila en los tres entornos de `platformio.ini`.
- `uv run pytest -q` pasa.
- `uv run ruff check .` sin hallazgos.
- Si cambia el formato del registro, `docs/03-esquema-de-datos.md` está
  actualizado y `ESQUEMA_DATOS` incrementado si el cambio es incompatible.

## Reglas específicas del proyecto

1. **Nunca** commitear `secrets.h`, credenciales ni datos crudos.
2. Durante una campaña de calibración activa, no modificar `config.h`
   ni el esquema de datos. Un cambio a mitad de campaña invalida los datos.
3. Todo coeficiente de calibración se deriva de datos, se documenta con su
   intervalo de validez y se acompaña de la campaña que lo produjo.
4. Los datos crudos no se editan. Las correcciones viven en la capa de análisis.
5. `aweighting_coeffs.h` se genera con `tools/gen_aweighting.py`, nunca se
   edita a mano.

## Entorno de desarrollo

```bash
# Firmware
cp firmware/include/secrets.example.h firmware/include/secrets.h
pio run -d firmware -e esp8266_d1mini

# Análisis
cd analysis && uv sync
```

Requiere PlatformIO Core >= 6.2.0 y el módulo `intelhex` para los builds de ESP32.
