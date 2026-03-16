"""
TFJA Monitor — Backend API
Deploy en Railway.app (gratis)
"""

import os
import re
import asyncio
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from playwright.async_api import async_playwright

app = Flask(__name__)

# Permitir peticiones desde GitHub Pages y localhost
CORS(app, origins=[
    "https://*.github.io",
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    # Agrega aquí tu URL de GitHub Pages cuando la tengas:
    # "https://TU_USUARIO.github.io"
    "*"  # Temporalmente abierto; restringir después si se desea
])

# ─────────────────────────────────────────────
# SCRAPER
# ─────────────────────────────────────────────

async def scrape_expediente(numero: str, fecha_hoy: str) -> dict:
    """
    Usa Playwright para buscar un expediente en el boletín del TFJA.
    Retorna dict con acuerdos encontrados y flag de actualización hoy.
    """
    resultado = {
        "expediente": numero,
        "fecha_buscada": fecha_hoy,
        "acuerdos": [],
        "tiene_actualizacion_hoy": False,
        "error": None,
        "timestamp": datetime.now().isoformat()
    }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-dev-shm-usage", "--disable-gpu"]
            )
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                locale="es-MX"
            )
            page = await ctx.new_page()

            # ── 1. Navegar ──────────────────────────────
            await page.goto(
                "https://www.tfja.gob.mx/boletin/jurisdiccional/",
                wait_until="domcontentloaded",
                timeout=45000
            )
            await page.wait_for_timeout(2000)

            # ── 2. Encontrar campo de expediente ────────
            # Intentar múltiples selectores posibles
            input_sel = None
            for sel in [
                "input[placeholder*='xpediente' i]",
                "input[name*='xpediente' i]",
                "input[id*='xpediente' i]",
                "input[type='text']:first-of-type",
                "input:not([type='submit']):not([type='button']):not([type='hidden'])"
            ]:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        input_sel = sel
                        break
                except:
                    pass

            if not input_sel:
                resultado["error"] = "No se encontró el campo de búsqueda. El sitio puede haber cambiado."
                await browser.close()
                return resultado

            # ── 3. Escribir número de expediente ────────
            await page.fill(input_sel, numero)
            await page.wait_for_timeout(500)

            # ── 4. Presionar el botón de consulta ───────
            boton_encontrado = False
            for sel in [
                "button:has-text('Consultar')",
                "button:has-text('Buscar')",
                "input[type='submit']",
                "button[type='submit']",
                "a:has-text('Consultar')"
            ]:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        boton_encontrado = True
                        break
                except:
                    pass

            if not boton_encontrado:
                await page.keyboard.press("Enter")

            # ── 5. Esperar resultados ────────────────────
            await page.wait_for_timeout(4000)
            try:
                await page.wait_for_selector("table tr, .resultado, .acuerdo", timeout=8000)
            except:
                pass

            # ── 6. Extraer datos ─────────────────────────
            # Intentar extraer filas de tabla
            rows = await page.query_selector_all("table tr")
            acuerdos = []

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                textos = []
                for cell in cells:
                    txt = (await cell.inner_text()).strip()
                    textos.append(txt)

                # Detectar si la fila tiene una fecha
                fecha_acuerdo = None
                descripcion = ""
                tipo = ""

                for txt in textos:
                    # Buscar fecha en formato dd-mm-yyyy o dd/mm/yyyy
                    m = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', txt)
                    if m:
                        d, mo, y = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
                        fecha_acuerdo = f"{d}-{mo}-{y}"
                    elif len(txt) > 5:
                        if not descripcion:
                            descripcion = txt[:300]
                        else:
                            tipo = txt[:150]

                if fecha_acuerdo:
                    acuerdo = {
                        "fecha": fecha_acuerdo,
                        "descripcion": descripcion or tipo or "Ver en portal",
                        "tipo": tipo,
                        "es_hoy": fecha_acuerdo == fecha_hoy
                    }
                    acuerdos.append(acuerdo)
                    if fecha_acuerdo == fecha_hoy:
                        resultado["tiene_actualizacion_hoy"] = True

            # Si no hubo tabla, buscar fechas en texto plano
            if not acuerdos:
                body_text = await page.inner_text("body")
                fechas = re.findall(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', body_text)
                vistas = set()
                for d, mo, y in fechas:
                    fecha_fmt = f"{d.zfill(2)}-{mo.zfill(2)}-{y}"
                    if fecha_fmt not in vistas:
                        vistas.add(fecha_fmt)
                        acuerdos.append({
                            "fecha": fecha_fmt,
                            "descripcion": "Acuerdo publicado — revisar portal para detalles completos",
                            "tipo": "",
                            "es_hoy": fecha_fmt == fecha_hoy
                        })
                        if fecha_fmt == fecha_hoy:
                            resultado["tiene_actualizacion_hoy"] = True

                # Verificar mensaje de "sin resultados"
                lower = body_text.lower()
                if not acuerdos and any(p in lower for p in [
                    "no se encontr", "sin resultado", "no hay registro",
                    "no existen", "no encontrado"
                ]):
                    resultado["error"] = "Expediente no encontrado en el boletín"

            resultado["acuerdos"] = acuerdos
            await browser.close()

    except Exception as e:
        resultado["error"] = f"Error técnico: {str(e)[:200]}"

    return resultado


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.route("/")
def health():
    return jsonify({
        "status": "ok",
        "service": "TFJA Monitor API",
        "version": "1.0.0"
    })


@app.route("/api/buscar", methods=["POST"])
def buscar():
    """
    POST /api/buscar
    Body: { "expedientes": "exp1; exp2; exp3", "fecha": "16-03-2026" }
    """
    data = request.get_json(silent=True) or {}
    raw = data.get("expedientes", "").strip()
    fecha = data.get("fecha", datetime.now().strftime("%d-%m-%Y"))

    if not raw:
        return jsonify({"error": "No se proporcionaron expedientes"}), 400

    lista = [e.strip() for e in re.split(r"[;,\n]", raw) if e.strip()]

    if len(lista) > 20:
        return jsonify({"error": "Máximo 20 expedientes por consulta"}), 400

    # Ejecutar búsquedas secuencialmente (Railway free tier tiene 1 CPU)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    resultados = []

    for exp in lista:
        r = loop.run_until_complete(scrape_expediente(exp, fecha))
        resultados.append(r)

    loop.close()

    con_actualizacion = [r for r in resultados if r["tiene_actualizacion_hoy"]]

    return jsonify({
        "fecha_consulta": fecha,
        "total": len(resultados),
        "con_actualizacion": len(con_actualizacion),
        "expedientes_actualizados": [r["expediente"] for r in con_actualizacion],
        "resultados": resultados
    })


@app.route("/api/fecha-hoy")
def fecha_hoy():
    hoy = datetime.now()
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return jsonify({
        "fecha": hoy.strftime("%d-%m-%Y"),
        "display": f"{hoy.day} de {meses[hoy.month-1]} de {hoy.year}",
        "timestamp": hoy.isoformat()
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
