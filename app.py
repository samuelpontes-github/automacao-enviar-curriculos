import os
import time
import re
import json
import asyncio
import requests
import psycopg2 
from datetime import datetime
from google import genai
from firecrawl import FirecrawlApp
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright

# Carrega arquivo .env apenas se ele existir localmente (bom para testes no seu PC)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =====================================================================
# LEITURA DAS CONFIGURAÇÕES VIA VARIÁVEIS DE AMBIENTE (.env)
# =====================================================================
HYPERBROWSER_API_KEY = os.environ.get("HYPERBROWSER_API_KEY")
URL_BANCO_DADOS = os.environ.get("URL_BANCO_DADOS")
GECKO_API_KEY = os.environ.get("GECKO_API_KEY")

# Inicialização das APIs puxando as variáveis de ambiente com segurança
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
firecrawl_app = FirecrawlApp(api_key=os.environ.get("FIRECRAWL_API_KEY"))

# Diretório e arquivo temporário para os Cookies
PASTA_DO_SCRIPT = os.path.dirname(os.path.abspath(__file__))
CAMINHO_JSON_COOKIES = os.path.join(PASTA_DO_SCRIPT, "estado_login_temp.json")

class EsquemaVaga(BaseModel):
    Descricao_vaga: str = Field(
        description="Texto descritivo sobre as atividades, atribuições e responsabilidades da vaga de emprego."
    )

# =====================================================================
# FUNÇÃO PARA RECONSTRUIR O ARQUIVO DE COOKIES EM TEMPO DE EXECUÇÃO
# =====================================================================
def preparar_cookies_ambiente():
    """Lê o texto do JSON salvo na variável de ambiente e gera o arquivo físico temporário."""
    conteudo_cookies_json = os.environ.get("CONTEUDO_ESTADO_LOGIN")
    
    if not conteudo_cookies_json:
        print("❌ Erro Crítico: A variável de ambiente 'CONTEUDO_ESTADO_LOGIN' não está definida!")
        return False
    
    try:
        # Valida se o texto recebido é um JSON válido e o escreve no arquivo
        dados_json = json.loads(conteudo_cookies_json)
        with open(CAMINHO_JSON_COOKIES, "w", encoding="utf-8") as f:
            json.dump(dados_json, f, ensure_ascii=False, indent=2)
        print("🍪 Arquivo temporário de cookies injetado com sucesso via ambiente!")
        return True
    except Exception as e:
        print(f"❌ Erro ao decodificar a string JSON de cookies: {e}")
        return False

# =====================================================================
# FUNÇÕES DE GERENCIAMENTO DO BANCO DE DADOS ONLINE
# =====================================================================
def inicializar_banco_online():
    try:
        conn = psycopg2.connect(URL_BANCO_DADOS)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidaturas (
                url TEXT PRIMARY KEY,
                titulo TEXT,
                data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("💾 Banco de dados online verificado/inicializado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao conectar ou inicializar o banco online: {e}")

def verificar_vaga_existente(url):
    try:
        conn = psycopg2.connect(URL_BANCO_DADOS)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM candidaturas WHERE url = %s", (url,))
        resultado = cursor.fetchone()
        cursor.close()
        conn.close()
        return resultado is not None
    except Exception as e:
        print(f"⚠️ Erro ao consultar banco online: {e}")
        return False

def salvar_vaga_no_banco(url, titulo):
    try:
        conn = psycopg2.connect(URL_BANCO_DADOS)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO candidaturas (url, titulo) VALUES (%s, %s) ON CONFLICT (url) DO NOTHING",
            (url, titulo)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print("💾 URL da vaga salva no banco de dados na nuvem!")
    except Exception as e:
        print(f"❌ Erro ao salvar vaga no banco online: {e}")

# =====================================================================
# FUNÇÃO DA AUTOMAÇÃO DO HYPERBROWSER (PLAYWRIGHT)
# =====================================================================
async def executar_candidatura_hyperbrowser(url_vaga, titulo_vaga):
    if not os.path.exists(CAMINHO_JSON_COOKIES):
        print(f"❌ Erro: O arquivo temporário de cookies não foi encontrado.")
        return False

    nome_print_limpo = re.sub(r'[\\/*?:"<>| ]', '_', titulo_vaga)[:30]
    caminho_print = os.path.join(PASTA_DO_SCRIPT, f"sucesso_{nome_print_limpo}.png")

    async with async_playwright() as p:
        print("🌐 Conectando ao Hyperbrowser...")
        browser = await p.chromium.connect_over_cdp(
            f"wss://connect.hyperbrowser.ai?apiKey={HYPERBROWSER_API_KEY}"
        )
        
        print("🍪 Injetando o estado de login completo...")
        context = await browser.new_context(storage_state=CAMINHO_JSON_COOKIES)
        page = await context.new_page()
        
        print(f"🚀 Acessando a página da vaga: {url_vaga}")
        await page.goto(url_vaga, wait_until="commit")
        
        seletor_botao = 'button[data-apply="normal"]:has-text("Quero me candidatar")'

        try:
            print("⏳ Aguardando o botão de candidatura ficar visível...")
            await page.wait_for_selector(seletor_botao, state="visible", timeout=12000)
            
            print("🎯 Botão encontrado! Clicando para se candidatar...")
            await page.click(seletor_botao)
            
            print("⏳ Aguardando 6 segundos para processamento e mudança de tela...")
            await page.wait_for_timeout(6000)

            print("📸 Tirando print de confirmação da candidatura...")
            await page.screenshot(path=caminho_print, full_page=False)
            print(f"✅ Sucesso! Candidatura confirmada. Print salvo em: {caminho_print}")
            
            await context.close()
            await browser.close()
            return True
            
        except Exception as e:
            print(f"❌ Erro ao tentar se candidatar via Hyperbrowser: {e}")
            caminho_erro = os.path.join(PASTA_DO_SCRIPT, f"erro_{nome_print_limpo}.png")
            await page.screenshot(path=caminho_erro)
            print(f"📸 Print da tela de erro salvo em: {caminho_erro}")
            
            await context.close()
            await browser.close()
            return False

# =====================================================================
# DISPARO INICIAL E ETAPA 1: BUSCA DE LISTAGEM
# =====================================================================
# Prepara os cookies e o banco online
if not preparar_cookies_ambiente():
    print("🛑 Encerrando execução devido a falha nos cookies de ambiente.")
    exit(1)

inicializar_banco_online()

print("Buscando listagem de vagas na GeckoAPI...")
response = requests.post(
    "https://api.geckoapi.com.br/v1/extract",
    headers={"Authorization": f"Bearer {GECKO_API_KEY}"},
    json={
        "target": "catho.com.br",
        "type": "plp",
        "page": 1,
        "jobTitle": "Jovem Aprendiz",
        "city": "Mogi das Cruzes",
        "state": "SP",
        "workModel": ["presential"]
    }
)

dados_api = response.json()
vagas_encontradas = dados_api.get("data", {}).get("items", [])
print(f"Foram retornadas {len(vagas_encontradas)} vagas na listagem.\n")

termos_obrigatorios = ["jovem aprendiz", "aprendiz"]
data_atual = datetime.now()

# =====================================================================
# ETAPA 2: VARREDURA, RASPAGEM E ANÁLISE EM LOOP
# =====================================================================
for vaga in vagas_encontradas:
    titulo = vaga.get("title", "")
    url_original = vaga.get("url")
    
    if any(termo in titulo.lower() for termo in termos_obrigatorios) and url_original:
        
        if verificar_vaga_existente(url_original):
            print(f"⏭️ Vaga pulada! O banco online confirmou que você já processou: '{titulo}'")
            continue
    
        print(f"\n🎯 Vaga nova e compatível encontrada no título: '{titulo}'")
        print(f"URL original: {url_original}")
        
        try:
            print("🕷️ Acionando Firecrawl para extrair dados estruturados...")
            resposta_firecrawl = firecrawl_app.scrape_url(
                url_original,
                params={
                    "formats": ["json"],
                    "jsonOptions": {
                        "schema": EsquemaVaga.model_json_schema()
                    },
                    "onlyMainContent": False
                },
                timeout=120000
            )
            
            bloco_json = getattr(resposta_firecrawl, "json", {}) or {}
            metadados_obj = getattr(resposta_firecrawl, "metadata", None)
            
            vaga_recente = False
            dias_publicada = None
            data_encontrada = None
            
            og_description = ""
            meta_description = ""
            if metadados_obj:
                og_description = getattr(metadados_obj, "ogDescription", "") or ""
                meta_description = getattr(metadados_obj, "description", "") or ""
            
            texto_para_busca = f"{og_description} {meta_description}"
            match_data = re.search(r"(\d{2}-\d{2}-\d{4})", texto_para_busca)
            
            if match_data:
                data_encontrada = match_data.group(1)
                try:
                    data_publicacao = datetime.strptime(data_encontrada, "%d-%m-%Y")
                    diferenca = data_atual - data_publicacao
                    dias_publicada = diferenca.days
                    if dias_publicada <= 15:
                        vaga_recente = True
                except Exception as date_parse_err:
                    print(f"⚠️ Erro ao converter a string de data '{data_encontrada}': {date_parse_err}")
                    vga_recente = True
            else:
                print("⚠️ Não foi encontrada uma data completa (DD-MM-YYYY) nos metadados. Passando por segurança.")
                vaga_recente = True

            if not vaga_recente and dias_publicada is not None:
                print(f"⏭️ Ignorando vaga antiga! Publicada em {data_encontrada} (há {dias_publicada} dias).")
                continue
            
            if dias_publicada is not None:
                print(f"📅 Vaga válida! Publicada em {data_encontrada} (há {dias_publicada} dias).")

            if isinstance(bloco_json, dict):
                descricao_vaga = bloco_json.get("Descricao_vaga") or bloco_json.get("descricao_vaga") or "Sem descrição"
            else:
                descricao_vaga = getattr(bloco_json, "Descricao_vaga", "") or getattr(bloco_json, "descricao_vaga", "") or "Sem descrição"
            
            print("✅ Detalhes coletados com sucesso!")
            print("🤖 Enviando para análise do Gemini-3.5-Flash...")
            
            prompt_ia = f"""
            Analise a descrição da vaga de emprego abaixo com foco em identificar se ela é estritamente aberta para quem NÃO tem experiência na função.

            Regras para responder SIM:
            - A descrição deve citar explicitamente termos como: "não é necessário ter experiência", "sem experiência", "não exige experiência", "aceita primeiro emprego", "fornecemos treinamento" ou ser explicitamente uma vaga de Jovem Aprendiz / Estágio que acolha iniciantes.

            Regras para responder NÃO:
            - Se a vaga exigir qualquer experiência prévia.
            - Se houver frases como "experiência desejável", "experiência será um diferencial", "a sua experiência importa" ou termos similares que valorizem histórico profissional anterior.
            - Se a descrição for totalmente neutra/silenciosa sobre aceitar pessoas sem experiência.

            Responda APENAS com a palavra "SIM" ou "NÃO". Não adicione pontos, justificativas ou textos extras.

            Descrição da vaga:
            Título: {titulo}
            Descrição: {descricao_vaga}
            """
            
            response_gemini = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt_ia,
            )
            
            resultado = response_gemini.text.strip().upper()
            print(f"🤖 A vaga aceita sem experiência: {resultado}")
            
            # =====================================================================
            # INTEGRAÇÃO HYPERBROWSER E SALVAMENTO NO BANCO ONLINE
            # =====================================================================
            if "SIM" in resultado:
                print("🚀 Condição aceita! Iniciando a candidatura automatizada com Hyperbrowser...")
                sucesso = asyncio.run(executar_candidatura_hyperbrowser(url_original, titulo))
                
                if sucesso:
                    salvar_vaga_no_banco(url_original, titulo)
                    time.sleep(2)
            else:
                print("⏭️ Vaga exige experiência. Pulando candidatura.")
                
        except Exception as e:
            print(f"❌ Falha no processamento da vaga: {e}")
            
        time.sleep(2)
    else:
        print(f"⏭️ Ignorando por título e economizando crédito para: '{titulo}'")

# Limpeza opcional do arquivo temporário de cookies após finalizar
if os.path.exists(CAMINHO_JSON_COOKIES):
    os.remove(CAMINHO_JSON_COOKIES)

print("\nCurrículos enviados pela automação e análise de IA finalizadas!")
