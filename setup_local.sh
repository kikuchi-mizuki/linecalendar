#!/bin/bash
set -e

# 1. Python仮想環境の作成
echo "[1/5] Python仮想環境を作成します..."
python3 -m venv venv
source venv/bin/activate

# 2. 依存パッケージのインストール
echo "[2/5] 依存パッケージをインストールします..."
pip install --upgrade pip
pip install -r requirements.txt

# 3. .envファイルの雛形作成
echo "[3/5] .envファイルの雛形を作成します..."
if [ ! -f .env ]; then
  cat <<EOF > .env
LINE_CHANNEL_SECRET=your_line_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
GOOGLE_CLIENT_SECRET_FILE=client_secret.json
FLASK_ENV=development
EOF
  echo ".envファイルを作成しました。値を自分のものに書き換えてください。"
else
  echo ".envファイルは既に存在します。"
fi

# 4. Google認証ファイル配置の案内
echo "[4/5] Google認証情報（client_secret.json）をプロジェクト直下に配置してください。"

# 5. ngrokのインストール案内
echo "[5/5] ngrokをインストールし、ローカルサーバーを外部公開してください。"
echo "ngrokのインストール: https://ngrok.com/download"
echo "ngrokの起動例: ngrok http 5000"

echo "---"
echo "セットアップ完了！"
echo "1. .envの値を正しく設定してください。"
echo "2. client_secret.jsonを配置してください。"
echo "3. 'source venv/bin/activate' で仮想環境を有効化してください。"
echo "4. 'flask run' または 'python app.py' でサーバーを起動してください。"
echo "5. ngrokで外部公開し、LINE DevelopersのWebhook URLをngrokのURLに設定してください。"
echo "---" 