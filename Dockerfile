FROM python:3.11
WORKDIR /app


# Poetryのインストール
RUN pip install poetry

# 仮想環境を作成しないように設定
RUN poetry config virtualenvs.create false

# pyproject.tomlとpoetry.lockをコピー
COPY pyproject.toml /app/

# 依存関係のインストール
RUN poetry install --no-root --no-interaction --no-ansi

# ソースコードをコンテナにコピー
COPY . .


# アプリケーションの実行コマンドを設定（FastAPIの場合）
CMD ["poetry", "run", "uvicorn", "main:app", "--host","0.0.0.0", "--port", "8080", "--reload"]