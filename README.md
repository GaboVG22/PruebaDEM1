# OpenTopo DEM Tester

Aplicación mínima para probar API Key de OpenTopography y descargar un DEM desde un KMZ/KML con punto de control.

## Funciones

- Cargar KMZ/KML con punto de control.
- Leer latitud y longitud.
- Calcular bbox desde margen en km o grados.
- Probar API Key de OpenTopography.
- Descargar DEM COP30, NASADEM, SRTMGL1 o SRTMGL3.
- Descargar en modo normal o por partes.
- Unir teselas en un GeoTIFF único si se usa modo por partes.

## Streamlit Cloud

Main file path:

```text
app.py
```

## Seguridad

La API Key se ingresa manualmente en la interfaz de Streamlit. No se guarda en el repositorio.
