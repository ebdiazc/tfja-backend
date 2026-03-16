"""
TFJA Monitor — Backend API (versión ligera, sin Playwright)
Deploy en Railway.app
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9",
    "Connection": "keep-alive",
}

BASE_URL = "https://www.tfja.gob.mx/boletin/jurisdiccional/"


def buscar_expediente(numero, fecha_hoy):
    resultado = {
        "expediente": numero,
        "fecha_buscada": fecha_hoy,
        "acuerdos": [],
        "tiene_actualizacion_hoy": False,
        "error": None,
        "timestamp": datetime.now().isoformat()
    }

    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        r = session.get(BASE_URL, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        form = soup.find("form")
        payload = {}

        if form:
            for inp in form.find_all("input"):
                if inp.get("type", "").lower() == "hidden" and inp.get("name"):
                    payload[inp["name"]] = inp.get("value", "")

            campo_exp = None
            for inp in form.find_all("input"):
                name = (inp.get("name") or "").lower()
                ph   = (inp.get("placeholder") or "").lower()
                iid  = (inp.get("id") or "").lower()
                if any("expediente" in x for x in [name, ph, iid]):
                    campo_exp = inp.get("name") or inp.get("id")
                    break
            if not campo_exp:
                for inp in form.find_all("input"):
                    if inp.get("type", "text").lower() in ("text", "search", "") and inp.get("name"):
                        campo_exp = inp["name"]
                        break

            payload[campo_exp or "expediente"] = numero
            action = form.get("action", BASE_URL)
            if not action.startswith("http"):
                action = "https://www.tfja.gob.mx" + action
            method = form.get("method", "post").lower()
        else:
            action = BASE_URL
            method = "post"
            payload = {"expediente": numero}

        if method == "post":
            resp = session.post(action, data=payload, timeout=20)
        else:
            resp = session.get(action, params={"expediente": numero}, timeout=20)

        resp.raise_for_status()
        soup2 = BeautifulSoup(resp.text, "html.parser")

        acuerdos = []
        for tabla in soup2.find_all("table"):
            for fila in tabla.find_all("tr"):
                celdas = fila.find_all("td")
                if len(celdas) < 2:
                    continue
                textos = [c.get_text(strip=True) for c in celdas]
                fecha_encontrada = None
                descripcion = ""
                for txt in textos:
                    m = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', txt)
                    if m:
                        fecha_encontrada = f"{m.group(1).zfill(2)}-{m.group(2).zfill(2)}-{m.group(3)}"
                    elif len(txt) > 5 and not descripcion:
                        descripcion = txt[:300]
                if fecha_encontrada:
                    es_hoy = fecha_encontrada == fecha_hoy
                    acuerdos.append({"fecha": fecha_encontrada, "descripcion": descripcion or "Ver en portal", "es_hoy": es_hoy})
                    if es_hoy:
                        resultado["tiene_actualizacion_hoy"] = True

        if not acuerdos:
            texto = soup2.get_text()
            vistas = set()
            for d, mo, y in re.findall(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', texto):
                fmt = f"{d.zfill(2)}-{mo.zfill(2)}-{y}"
                if fmt not in vistas:
                    vistas.add(fmt)
                    es_hoy = fmt == fecha_hoy
                    acuerdos.append({"fecha": fmt, "descripcion": "Acuerdo publicado — revisar portal", "es_hoy": es_hoy})
                    if es_hoy:
                        resultado["tiene_actualizacion_hoy"] = True
            if not acuerdos:
                lower = texto.lower()
                if any(p in lower for p in ["no se encontr", "sin resultado", "no hay registro"]):
                    resultado["error"] = "Expediente no encontrado en el boletín"
                else:
                    resultado["error"] = "No se pudieron extraer resultados. Verifique el número."

        resultado["acuerdos"] = acuerdos

    except requests.exceptions.Timeout:
        resultado["error"] = "Tiempo de espera agotado al conectar con el TFJA"
    except requests.exceptions.ConnectionError:
        resultado["error"] = "No se pudo conectar con tfja.gob.mx"
    except Exception as e:
        resultado["error"] = f"Error técnico: {str(e)[:200]}"

    return resultado


@app.route("/")
def health():
    return jsonify({"status": "ok", "service": "TFJA Monitor API", "version": "2.0.0"})


@app.route("/api/buscar", methods=["POST"])
def buscar():
    data  = request.get_json(silent=True) or {}
    raw   = data.get("expedientes", "").strip()
    fecha = data.get("fecha", datetime.now().strftime("%d-%m-%Y"))
    if not raw:
        return jsonify({"error": "No se proporcionaron expedientes"}), 400
    lista = [e.strip() for e in re.split(r"[;,\n]", raw) if e.strip()]
    if len(lista) > 20:
        return jsonify({"error": "Máximo 20 expedientes por consulta"}), 400
    resultados = [buscar_expediente(exp, fecha) for exp in lista]
    con_act = [r for r in resultados if r["tiene_actualizacion_hoy"]]
    return jsonify({
        "fecha_consulta": fecha,
        "total": len(resultados),
        "con_actualizacion": len(con_act),
        "expedientes_actualizados": [r["expediente"] for r in con_act],
        "resultados": resultados
    })


@app.route("/api/fecha-hoy")
def fecha_hoy():
    hoy = datetime.now()
    meses = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return jsonify({"fecha": hoy.strftime("%d-%m-%Y"), "display": f"{hoy.day} de {meses[hoy.month-1]} de {hoy.year}", "timestamp": hoy.isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
