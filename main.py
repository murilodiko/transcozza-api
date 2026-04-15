"""
TRANSCOZZA VIAGENS - Backend FastAPI
Correções: Resend para e-mail + uploads paralelos
"""
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
import uuid
import random
import string
import asyncio
import httpx
import tempfile
import subprocess
import zipfile
import io
from fastapi.responses import StreamingResponse
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas as rl_canvas
import pdfplumber
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ─── Supabase ───────────────────────────────────────────
SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
SUPABASE_BUCKET     = "viagens-docs"
supabase: Client    = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

# ─── Resend ─────────────────────────────────────────────
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM     = os.getenv("EMAIL_FROM", "viagens@transcozza.com.br")

# ─── App ────────────────────────────────────────────────
app = FastAPI(title="Transcozza Viagens API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Models ─────────────────────────────────────────────
class CriarViagemRequest(BaseModel):
    container: str
    di: str
    motorista: str
    placa: Optional[str] = ""
    email_cliente: Optional[str] = ""
    email_despachante: Optional[str] = ""
    email_operador: Optional[str] = ""

# ─── Helpers ────────────────────────────────────────────
def gerar_trip_code(length=6):
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        result = supabase.table("viagens").select("id").eq("trip_code", code).execute()
        if not result.data:
            return code

async def enviar_email_resend(destinatarios: List[str], assunto: str, corpo_html: str):
    if not RESEND_API_KEY or not destinatarios:
        print("Resend API key ausente ou sem destinatários")
        return False
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": f"Transcozza Express <{EMAIL_FROM}>", "to": destinatarios, "subject": assunto, "html": corpo_html}
            )
            ok = resp.status_code in [200, 201]
            print(f"{'OK' if ok else 'ERRO'} Resend {resp.status_code}: {resp.text[:200]}")
            return ok
        except Exception as e:
            print(f"Erro Resend: {e}")
            return False

def fotos_html(urls):
    imgs = "".join([f'<a href="{u}" target="_blank"><img src="{u}" style="width:180px;height:135px;object-fit:cover;border-radius:8px;border:2px solid #e0e0e0;margin:6px"/></a>' for u in urls])
    return f'<div style="background:white;padding:20px;border-radius:10px;text-align:center"><h3 style="margin:0 0 16px;color:#333">Documentos Fotográficos</h3>{imgs}</div>'

def base_email(titulo, cor, icone, viagem, extra):
    return f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f4f6f8;padding:24px;border-radius:12px">
      <div style="background:#0a0e1a;padding:24px;border-radius:10px;text-align:center;margin-bottom:20px">
        <h1 style="color:{cor};margin:0;font-size:22px">{icone} Transcozza Express</h1>
        <p style="color:#6b7fa3;margin:8px 0 0;font-size:14px">{titulo}</p>
      </div>
      <div style="background:white;padding:24px;border-radius:10px;margin-bottom:16px">
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr><td style="padding:10px 8px;color:#666;width:130px;border-bottom:1px solid #f0f0f0">Container</td><td style="padding:10px 8px;font-weight:700;border-bottom:1px solid #f0f0f0">{viagem['container']}</td></tr>
          <tr><td style="padding:10px 8px;color:#666;border-bottom:1px solid #f0f0f0">DI</td><td style="padding:10px 8px;font-weight:700;border-bottom:1px solid #f0f0f0">{viagem['di']}</td></tr>
          <tr><td style="padding:10px 8px;color:#666;border-bottom:1px solid #f0f0f0">Motorista</td><td style="padding:10px 8px;border-bottom:1px solid #f0f0f0">{viagem['motorista']}</td></tr>
          <tr><td style="padding:10px 8px;color:#666;border-bottom:1px solid #f0f0f0">Placa</td><td style="padding:10px 8px;border-bottom:1px solid #f0f0f0">{viagem.get('placa','—')}</td></tr>
          <tr><td style="padding:10px 8px;color:#666">Data/Hora</td><td style="padding:10px 8px">{datetime.now().strftime('%d/%m/%Y às %H:%M')}</td></tr>
        </table>
      </div>
      {extra}
      <p style="text-align:center;color:#aaa;font-size:12px;margin-top:16px">Transcozza Express · Sistema automático</p>
    </div>"""

# ─── Routes ─────────────────────────────────────────────
@app.get("/")
def health():
    return {"status": "ok", "service": "Transcozza Viagens API", "version": "2.0.0"}

@app.post("/viagens")
async def criar_viagem(body: CriarViagemRequest):
    trip_code = gerar_trip_code()
    data = {
        "trip_code": trip_code,
        "container": body.container.upper().strip(),
        "di": body.di.strip(),
        "motorista": body.motorista.strip(),
        "placa": body.placa.strip() if body.placa else "",
        "email_cliente": body.email_cliente.strip() if body.email_cliente else "",
        "email_despachante": body.email_despachante.strip() if body.email_despachante else "",
        "email_operador": body.email_operador.strip() if body.email_operador else "",
        "status": "ativa",
        "step1_status": "pendente",
        "step2_status": "pendente",
        "step3_status": "pendente",
    }
    result = supabase.table("viagens").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Erro ao criar viagem")
    return {"success": True, "trip_code": trip_code, "viagem": result.data[0]}

@app.get("/viagens")
async def listar_viagens(status: Optional[str] = None):
    query = supabase.table("viagens").select("*").order("created_at", desc=True)
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return {"viagens": result.data or []}

@app.get("/viagens/{trip_code}")
async def buscar_viagem(trip_code: str):
    result = supabase.table("viagens").select("*").eq("trip_code", trip_code.upper()).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Viagem não encontrada")
    viagem = result.data[0]
    docs = supabase.table("documentos").select("*").eq("trip_code", trip_code.upper()).execute()
    viagem["documentos"] = docs.data or []
    return viagem

@app.post("/viagens/{trip_code}/etapa/{etapa}")
async def upload_etapa(trip_code: str, etapa: int, fotos: List[UploadFile] = File(...)):
    if etapa not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail="Etapa inválida")

    result = supabase.table("viagens").select("*").eq("trip_code", trip_code.upper()).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Viagem não encontrada")
    viagem = result.data[0]

    # Ler arquivos
    fotos_data = []
    for foto in fotos:
        conteudo = await foto.read()
        ext = foto.filename.split(".")[-1] if "." in foto.filename else "jpg"
        fotos_data.append({
            "conteudo": conteudo,
            "filename": foto.filename,
            "content_type": foto.content_type or "image/jpeg",
            "storage_path": f"{trip_code}/etapa{etapa}/{uuid.uuid4()}.{ext}",
        })

    # Upload paralelo
    loop = asyncio.get_event_loop()
    async def fazer_upload(f):
        await loop.run_in_executor(None, lambda: supabase.storage.from_(SUPABASE_BUCKET).upload(
            f["storage_path"], f["conteudo"], {"content-type": f["content_type"], "upsert": "true"}
        ))
        return supabase.storage.from_(SUPABASE_BUCKET).get_public_url(f["storage_path"])

    foto_urls = list(await asyncio.gather(*[fazer_upload(f) for f in fotos_data]))

    # Salvar documentos
    supabase.table("documentos").insert([{
        "viagem_id": viagem["id"],
        "trip_code": trip_code.upper(),
        "etapa": etapa,
        "tipo": ["retirada","cte","devolucao"][etapa-1],
        "storage_path": fotos_data[i]["storage_path"],
        "storage_url": foto_urls[i],
        "filename": fotos_data[i]["filename"],
    } for i in range(len(fotos_data))]).execute()

    # Atualizar status
    supabase.table("viagens").update({
        f"step{etapa}_status": "enviado",
        f"step{etapa}_at": datetime.utcnow().isoformat(),
    }).eq("trip_code", trip_code.upper()).execute()

    # Verificar conclusão
    v = supabase.table("viagens").select("*").eq("trip_code", trip_code.upper()).execute().data[0]
    if all(v[f"step{i}_status"] == "enviado" for i in [1,2,3]):
        supabase.table("viagens").update({"status": "concluida"}).eq("trip_code", trip_code.upper()).execute()

    # E-mail em background — NÃO bloqueia a resposta
    asyncio.create_task(_enviar_email_etapa(etapa, viagem, foto_urls))

    return {"success": True, "etapa": etapa, "fotos": len(foto_urls), "urls": foto_urls}

def parse_emails(campo: str) -> List[str]:
    """Aceita e-mails separados por vírgula ou ponto e vírgula"""
    if not campo:
        return []
    emails = [e.strip() for e in campo.replace(";", ",").split(",")]
    return [e for e in emails if e and "@" in e]

async def _enviar_email_etapa(etapa, viagem, urls):
    destinatarios = []
    if etapa == 1:
        destinatarios = parse_emails(viagem.get("email_cliente", ""))
        assunto = f"📦 [{viagem['container']}] Retirada do Container Confirmada"
        corpo = base_email("Retirada do Container", "#00d4ff", "📦", viagem, fotos_html(urls))
    elif etapa == 2:
        destinatarios = parse_emails(viagem.get("email_operador", ""))
        assunto = f"🗂️ [{viagem['container']}] CTE Carimbado Recebido"
        corpo = base_email("CTE Carimbado", "#ff6b35", "🗂️", viagem, fotos_html(urls))
    elif etapa == 3:
        destinatarios = (
            parse_emails(viagem.get("email_cliente", "")) +
            parse_emails(viagem.get("email_despachante", ""))
        )
        assunto = f"✅ [{viagem['container']}] Container Devolvido"
        corpo = base_email("Devolução do Container", "#00ff88", "✅", viagem, fotos_html(urls))
    else:
        return

    # Remove duplicatas mantendo ordem
    vistos = set()
    destinatarios = [e for e in destinatarios if not (e in vistos or vistos.add(e))]

    sucesso = await enviar_email_resend(destinatarios, assunto, corpo)
    for dest in destinatarios:
        supabase.table("email_logs").insert({
            "viagem_id": viagem["id"],
            "trip_code": viagem["trip_code"],
            "etapa": etapa,
            "destinatario": dest,
            "status": "enviado" if sucesso else "erro",
        }).execute()

@app.delete("/viagens/{trip_code}")
async def deletar_viagem(trip_code: str):
    result = supabase.table("viagens").select("id").eq("trip_code", trip_code.upper()).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Viagem não encontrada")
    supabase.table("viagens").update({"status": "cancelada"}).eq("trip_code", trip_code.upper()).execute()
    return {"success": True}

# ─── CTE: Remover valores ────────────────────────────────

def processar_cte_remover_valores(pdf_bytes: bytes, filename: str) -> bytes:
    """
    Remove a seção COMPONENTES DO VALOR DA PRESTAÇÃO DE SERVIÇO do CTE.
    Replica exatamente o comportamento do iLovePDF:
    retângulo branco dentro das bordas laterais, preservando linhas do documento.
    """
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.colors import white

    pdf_stream = io.BytesIO(pdf_bytes)

    with pdfplumber.open(pdf_stream) as pdf:
        page = pdf.pages[0]
        ph, pw = page.height, page.width
        words = page.extract_words()
        lines = page.lines

    # Detectar bordas laterais do documento na área de valores
    x_lefts  = [l['x0'] for l in lines if abs(l['x0'] - l['x1']) < 1 and 490 < l['top'] < 570]
    x_rights = [l['x1'] for l in lines if abs(l['x0'] - l['x1']) < 1 and 490 < l['top'] < 570]
    x_left  = min(x_lefts)  if x_lefts  else 20.0
    x_right = max(x_rights) if x_rights else 575.0

    # Detectar coordenadas da seção de valores
    y_tops, y_bots = [], []
    for w in words:
        txt = w['text'].upper()
        if 'COMPONENTES' in txt and w['top'] > 400:
            y_tops.append(w['top'])
        if ('RECEBER' in txt or ('SERVIÇO' in txt and w['top'] > 500)):
            y_bots.append(w['bottom'])

    y_top_pl = (min(y_tops) - 0.5) if y_tops else 502.0
    y_bot_pl = min((max(y_bots) + 0.5) if y_bots else 562.0, 562.0)

    # Converter para coords PDF (origem base-esquerda)
    pdf_y_base  = ph - y_bot_pl
    rect_height = y_bot_pl - y_top_pl
    rect_width  = x_right - x_left

    # Criar overlay com retângulo branco DENTRO das bordas (igual iLovePDF)
    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
    c.setFillColor(white)
    c.setStrokeColor(white)
    c.rect(x_left, pdf_y_base, rect_width, rect_height, fill=1, stroke=0)
    c.save()
    packet.seek(0)

    # Aplicar por cima do original
    overlay_reader = PdfReader(packet)
    original_reader = PdfReader(io.BytesIO(pdf_bytes))
    orig_page = original_reader.pages[0]
    orig_page.merge_page(overlay_reader.pages[0], over=True)

    writer = PdfWriter()
    writer.add_page(orig_page)

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    return out_buf.read()


@app.post("/cte/remover-valores")
async def cte_remover_valores(arquivos: List[UploadFile] = File(...)):
    """
    Recebe um ou mais PDFs de CTE e retorna ZIP com os PDFs processados
    (seção de valores removida).
    """
    resultados = []
    erros = []

    for arquivo in arquivos:
        conteudo = await arquivo.read()
        nome_original = arquivo.filename or "cte.pdf"
        nome_saida = nome_original.replace('.pdf', '_sem_valores.pdf').replace('.PDF', '_sem_valores.pdf')

        try:
            pdf_processado = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda c=conteudo, n=nome_original: processar_cte_remover_valores(c, n)
            )
            resultados.append((nome_saida, pdf_processado))
        except Exception as e:
            erros.append(f"{nome_original}: {str(e)}")

    if not resultados:
        raise HTTPException(status_code=500, detail=f"Erro ao processar: {'; '.join(erros)}")

    # Se apenas 1 arquivo, retornar PDF direto
    if len(resultados) == 1 and not erros:
        nome, dados = resultados[0]
        return StreamingResponse(
            io.BytesIO(dados),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{nome}"'}
        )

    # Múltiplos arquivos: retornar ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for nome, dados in resultados:
            zf.writestr(nome, dados)
        if erros:
            zf.writestr('ERROS.txt', '\n'.join(erros))

    zip_buf.seek(0)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="ctes_sem_valores.zip"'}
    )
