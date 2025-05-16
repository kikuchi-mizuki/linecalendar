FROM python:3.11-slim

# システムの依存関係をインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリを設定
WORKDIR /app

# 依存関係ファイルをコピー
COPY requirements.txt .

# Python仮想環境を作成し、パッケージをインストール
RUN python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをコピー
COPY . .

# 環境変数を設定
ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8000
ENV PORT=8000

# デバッグ用CMD: PORTと環境変数を表示して60秒スリープ
CMD sh -c "echo PORT=\$PORT; env; sleep 60"

# アプリケーションを実行
CMD sh -c "gunicorn app:app --bind 0.0.0.0:${PORT}" 