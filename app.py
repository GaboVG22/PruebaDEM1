
import streamlit as st
import zipfile
import tempfile
import re
import math
from pathlib import Path
from urllib.parse import urlencode
import requests
import pandas as pd

st.set_page_config(
    page_title="OpenTopo DEM Tester",
    page_icon="🛰️",
    layout="wide"
)

BASE_URL = "https://portal.opentopography.org/API/globaldem"


def extract_kml_text(uploaded_file):
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    if name.endswith(".kmz"):
        with zipfile.ZipFile(__import__("io").BytesIO(data), "r") as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError("El KMZ no contiene archivo KML.")
            return z.read(kml_names[0]).decode("utf-8", errors="ignore")
    if name.endswith(".kml"):
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Debe cargar un archivo KMZ o KML.")


def parse_first_point(kml_text):
    # Busca la primera coordenada tipo lon,lat,z o lon,lat dentro del KML.
    coords = re.findall(r"<coordinates[^>]*>(.*?)</coordinates>", kml_text, flags=re.DOTALL | re.IGNORECASE)
    if not coords:
        raise ValueError("No se encontraron coordenadas en el KML/KMZ.")
    for block in coords:
        parts = re.split(r"\s+", block.strip())
        for p in parts:
            vals = p.split(",")
            if len(vals) >= 2:
                try:
                    lon = float(vals[0])
                    lat = float(vals[1])
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        # Nombre Placemark, si existe antes del bloque.
                        name_match = re.search(r"<name[^>]*>(.*?)</name>", kml_text, flags=re.DOTALL | re.IGNORECASE)
                        name = re.sub("<.*?>", "", name_match.group(1)).strip() if name_match else "Punto de control"
                        return {"name": name, "lat": lat, "lon": lon}
                except Exception:
                    continue
    raise ValueError("No se pudo interpretar una coordenada válida lon,lat.")


def bbox_from_margin(lat, lon, margin_value, margin_unit):
    if margin_value <= 0:
        raise ValueError("El margen debe ser mayor que cero.")
    if margin_unit == "km":
        dlat = margin_value / 111.32
        cos_lat = max(math.cos(math.radians(lat)), 0.01)
        dlon = margin_value / (111.32 * cos_lat)
    else:
        dlat = margin_value
        dlon = margin_value
    return {
        "south": round(max(-90.0, lat - dlat), 8),
        "north": round(min(90.0, lat + dlat), 8),
        "west": round(max(-180.0, lon - dlon), 8),
        "east": round(min(180.0, lon + dlon), 8),
    }


def bbox_area_km2(bbox):
    radius_km = 6371.0088
    south = math.radians(bbox["south"])
    north = math.radians(bbox["north"])
    west = math.radians(bbox["west"])
    east = math.radians(bbox["east"])
    return (radius_km**2) * abs(math.sin(north) - math.sin(south)) * abs(east - west)


def build_url(dem_type, bbox, api_key_hidden="API_KEY_OCULTA"):
    params = {
        "demtype": dem_type,
        "south": bbox["south"],
        "north": bbox["north"],
        "west": bbox["west"],
        "east": bbox["east"],
        "outputFormat": "GTiff",
        "API_Key": api_key_hidden,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def split_bbox(bbox, rows, cols):
    south, north, west, east = bbox["south"], bbox["north"], bbox["west"], bbox["east"]
    tiles = []
    for i in range(rows):
        s = south + (north - south) * i / rows
        n = south + (north - south) * (i + 1) / rows
        for j in range(cols):
            w = west + (east - west) * j / cols
            e = west + (east - west) * (j + 1) / cols
            tiles.append({
                "tile": f"T{i+1:02d}_{j+1:02d}",
                "south": round(s, 8),
                "north": round(n, 8),
                "west": round(w, 8),
                "east": round(e, 8),
            })
    return tiles


def download_dem(dem_type, bbox, api_key, timeout=(15, 300)):
    if not api_key or not api_key.strip():
        raise ValueError("Debe ingresar API Key de OpenTopography.")
    params = {
        "demtype": dem_type,
        "south": bbox["south"],
        "north": bbox["north"],
        "west": bbox["west"],
        "east": bbox["east"],
        "outputFormat": "GTiff",
        "API_Key": api_key.strip(),
    }
    r = requests.get(BASE_URL, params=params, timeout=timeout)
    if r.status_code == 401:
        raise RuntimeError("Error 401: API Key no autorizada. Revisa la clave.")
    if r.status_code == 400:
        raise RuntimeError(f"Error 400: parámetros no válidos. Respuesta: {r.text[:500]}")
    if r.status_code == 204:
        raise RuntimeError("Error 204: sin datos para el bbox solicitado.")
    if r.status_code >= 400:
        raise RuntimeError(f"OpenTopography respondió HTTP {r.status_code}: {r.text[:500]}")

    data = r.content
    if not data:
        raise RuntimeError("Respuesta vacía desde OpenTopography.")

    looks_tiff = data.startswith(b"II*\x00") or data.startswith(b"MM\x00*")
    if not looks_tiff:
        txt = data[:800].decode("utf-8", errors="ignore")
        raise RuntimeError("La respuesta no parece GeoTIFF válido. Primeros caracteres:\n" + txt)
    return data


def mosaic_geotiffs(tile_paths):
    import rasterio
    from rasterio.merge import merge
    import io

    srcs = []
    try:
        for p in tile_paths:
            srcs.append(rasterio.open(p))
        mosaic, transform = merge(srcs)
        meta = srcs[0].meta.copy()
        meta.update({
            "driver": "GTiff",
            "height": mosaic.shape[1],
            "width": mosaic.shape[2],
            "transform": transform,
            "compress": "deflate",
            "predictor": 2,
        })
        with rasterio.io.MemoryFile() as mem:
            with mem.open(**meta) as dst:
                dst.write(mosaic)
            return mem.read()
    finally:
        for s in srcs:
            try:
                s.close()
            except Exception:
                pass


st.title("🛰️ OpenTopo DEM Tester")
st.caption("Aplicación mínima para probar API Key de OpenTopography y descargar DEM COP30 desde un KMZ/KML con punto de control.")

with st.sidebar:
    st.header("1 · Entrada")
    uploaded = st.file_uploader("KMZ/KML punto de control", type=["kmz", "kml"])
    api_key = st.text_input("API Key OpenTopography", type="password")
    dem_type = st.selectbox("DEM", ["COP30", "NASADEM", "SRTMGL1", "SRTMGL3"], index=0)

    st.header("2 · Bbox")
    margin_unit = st.radio("Unidad de margen", ["km", "grados"], horizontal=True)
    default_margin = 40.0 if margin_unit == "km" else 0.40
    margin = st.number_input("Margen desde punto", min_value=0.001, value=default_margin, step=5.0 if margin_unit == "km" else 0.05)

    st.header("3 · Descarga")
    mode = st.selectbox("Modo", ["Normal", "Por partes"], index=0)
    rows = st.selectbox("Filas", [1, 2, 3, 4], index=1)
    cols = st.selectbox("Columnas", [1, 2, 3, 4], index=1)

if uploaded is None:
    st.info("Carga un KMZ/KML con el punto de control. Luego ingresa tu API Key y presiona descargar.")
    st.stop()

try:
    kml = extract_kml_text(uploaded)
    point = parse_first_point(kml)
    bbox = bbox_from_margin(point["lat"], point["lon"], margin, margin_unit)
    area = bbox_area_km2(bbox)
except Exception as exc:
    st.error(str(exc))
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latitud", f"{point['lat']:.8f}")
c2.metric("Longitud", f"{point['lon']:.8f}")
c3.metric("Área bbox", f"{area:,.1f} km²")
c4.metric("DEM", dem_type)

st.subheader("Punto detectado")
st.json(point)

st.subheader("Bounding box")
st.json(bbox)

st.subheader("URL de prueba sin exponer clave")
st.code(build_url(dem_type, bbox), language="text")

if area > 30000:
    st.warning("El bbox es muy grande para una prueba inicial. Se recomienda reducir margen o usar modo por partes.")
elif area > 10000:
    st.info("Área grande. Para prueba de API Key, conviene modo normal con margen menor o modo por partes.")

if mode == "Por partes":
    tiles = split_bbox(bbox, rows, cols)
    st.subheader("Teselas")
    st.dataframe(pd.DataFrame(tiles), use_container_width=True)

if st.button("Descargar DEM GeoTIFF", type="primary"):
    try:
        progress = st.progress(0)
        status = st.empty()

        if mode == "Normal":
            status.info("Descargando DEM en una solicitud...")
            dem_bytes = download_dem(dem_type, bbox, api_key)
            progress.progress(100)
            st.success(f"DEM descargado correctamente: {len(dem_bytes)/(1024*1024):.2f} MB")
            st.download_button(
                "Descargar DEM GeoTIFF",
                data=dem_bytes,
                file_name=f"DEM_{dem_type}_{point['name'].replace(' ', '_')}.tif",
                mime="image/tiff",
            )
        else:
            import tempfile
            tmpdir = Path(tempfile.mkdtemp(prefix="opentopo_tiles_"))
            tile_paths = []
            tiles = split_bbox(bbox, rows, cols)
            logs = []
            for idx, tb in enumerate(tiles, start=1):
                status.info(f"Descargando tesela {idx}/{len(tiles)}: {tb['tile']}")
                tbbox = {k: tb[k] for k in ["south", "north", "west", "east"]}
                data = download_dem(dem_type, tbbox, api_key)
                fp = tmpdir / f"{tb['tile']}.tif"
                fp.write_bytes(data)
                tile_paths.append(fp)
                logs.append({"tile": tb["tile"], "MB": round(len(data)/(1024*1024), 3)})
                progress.progress(int(idx / len(tiles) * 80))

            status.info("Uniendo teselas en un GeoTIFF único...")
            dem_bytes = mosaic_geotiffs(tile_paths)
            progress.progress(100)
            st.success(f"DEM por partes descargado y unido correctamente: {len(dem_bytes)/(1024*1024):.2f} MB")
            st.dataframe(pd.DataFrame(logs), use_container_width=True)
            st.download_button(
                "Descargar DEM GeoTIFF unificado",
                data=dem_bytes,
                file_name=f"DEM_{dem_type}_{point['name'].replace(' ', '_')}_unificado.tif",
                mime="image/tiff",
            )

    except Exception as exc:
        st.error(str(exc))
        st.stop()

st.divider()
st.caption("La API Key se ingresa en la sesión de Streamlit y no se guarda en archivos del repositorio.")
