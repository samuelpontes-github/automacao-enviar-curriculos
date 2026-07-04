# Usa uma imagem oficial e leve do Python
FROM python:3.11-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia apenas os arquivos necessários para a automação de vagas
COPY requirements.txt ./
COPY app.py ./

# Instala as dependências Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Como o robô roda via FastCron/Script e não é uma API web (como Flask), 
# não precisamos expor portas (EXPOSE). O Railway executará o script diretamente.

# Comando para iniciar o seu robô
CMD ["python", "app.py"]
