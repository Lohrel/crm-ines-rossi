"""Os scripts de backup e restauração (docker/backup) com arquivos cortados ou estragados.

Rodam os scripts de verdade contra um banco à parte, criado e apagado aqui, com dados
fictícios. Precisam do pg_dump, do pg_restore e do gpg (no servidor, a imagem do backup já
os tem); sem eles, os testes são pulados.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest
from django.conf import settings
from psycopg import sql

PASTA_DOS_SCRIPTS = Path(settings.BASE_DIR) / "docker" / "backup"
BANCO = "crm_teste_backup"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(programa) for programa in ("pg_dump", "pg_restore", "gpg", "tar")),
    reason="precisa do pg_dump, do pg_restore e do gpg",
)


def _conectar(banco: str):
    config = settings.DATABASES["default"]
    return psycopg.connect(
        dbname=banco,
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"],
        autocommit=True,
    )


def _consultar(comando: str) -> list[tuple]:
    with _conectar(BANCO) as conexao:
        cursor = conexao.execute(comando)
        return cursor.fetchall() if cursor.description else []


@pytest.fixture
def ambiente(tmp_path):
    """Um banco com clientes fictícios, uma pasta de anexos e o .env do backup."""
    with _conectar(settings.DATABASES["default"]["NAME"]) as conexao:
        conexao.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(BANCO)))
        conexao.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(BANCO)))
    _consultar("CREATE TABLE cliente (id serial PRIMARY KEY, nome text NOT NULL)")
    _consultar(
        "INSERT INTO cliente (nome) SELECT 'Cliente Fictício ' || n FROM generate_series(1, 5000) n"
    )
    anexos = tmp_path / "anexos"
    (anexos / "clientes" / "1").mkdir(parents=True)
    (anexos / "clientes" / "1" / "contrato.pdf").write_bytes(b"%PDF-1.4 contrato ficticio")
    # O gpg-agent não aceita um caminho longo para o socket: a pasta do gpg fica em /tmp.
    gnupg = tempfile.mkdtemp(prefix="gpg-", dir="/tmp")  # noqa: S108
    config = settings.DATABASES["default"]
    env = {
        **os.environ,
        "BACKUP_PASSPHRASE": "senha-ficticia-do-backup",
        "BACKUP_DIR": str(tmp_path / "backups"),
        "ANEXOS_DIR": str(anexos),
        "POSTGRES_DB": BANCO,
        "POSTGRES_USER": config["USER"],
        "POSTGRES_PASSWORD": config["PASSWORD"],
        "POSTGRES_HOST": config["HOST"],
        "POSTGRES_PORT": str(config["PORT"]),
        "GNUPGHOME": gnupg,
    }
    yield env
    subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, check=False)  # noqa: S607
    shutil.rmtree(gnupg, ignore_errors=True)
    with _conectar(settings.DATABASES["default"]["NAME"]) as conexao:
        conexao.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(BANCO))
        )


def _rodar(script: str, env: dict, *argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        ["bash", str(PASTA_DOS_SCRIPTS / script), *argumentos],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _fazer_backup(env: dict) -> tuple[Path, Path]:
    resultado = _rodar("fazer-backup.sh", env)
    assert resultado.returncode == 0, resultado.stderr
    diario = Path(env["BACKUP_DIR"]) / "diario"
    banco = next(diario.glob("*.dump.gpg"))
    return banco, banco.with_name(banco.name.replace(".dump.gpg", "_anexos.tar.gpg"))


def _quantos_clientes() -> int:
    return _consultar("SELECT count(*) FROM cliente")[0][0]


def _cortar(origem: Path, destino: Path, fracao: float) -> None:
    conteudo = origem.read_bytes()
    destino.write_bytes(conteudo[: int(len(conteudo) * fracao)])


def test_backup_e_restauracao(ambiente):
    _fazer_backup(ambiente)
    _consultar("DELETE FROM cliente WHERE id > 10")
    contrato = Path(ambiente["ANEXOS_DIR"]) / "clientes" / "1" / "contrato.pdf"
    contrato.unlink()

    backup = next((Path(ambiente["BACKUP_DIR"]) / "diario").glob("*.dump.gpg"))
    resultado = _rodar("restaurar.sh", ambiente, f"diario/{backup.name}")

    assert resultado.returncode == 0, resultado.stderr
    assert _quantos_clientes() == 5000
    assert contrato.read_bytes() == b"%PDF-1.4 contrato ficticio"


@pytest.mark.parametrize("fracao", [0.5, 0.95])
def test_backup_do_banco_cortado_nao_apaga_os_dados_atuais(ambiente, fracao):
    banco, anexos = _fazer_backup(ambiente)
    _consultar("INSERT INTO cliente (nome) VALUES ('Cliente de depois do backup')")
    pasta = Path(ambiente["BACKUP_DIR"]) / "copia"
    pasta.mkdir()
    # Como uma cópia interrompida para o HD externo: o arquivo do banco ficou pela metade.
    _cortar(banco, pasta / banco.name, fracao)
    shutil.copy(anexos, pasta / anexos.name)

    resultado = _rodar("restaurar.sh", ambiente, f"copia/{banco.name}")

    assert resultado.returncode != 0
    assert "Nenhum dado foi alterado" in resultado.stderr
    assert _quantos_clientes() == 5001


def test_backup_do_banco_alterado_nao_apaga_os_dados_atuais(ambiente):
    banco, _ = _fazer_backup(ambiente)
    conteudo = bytearray(banco.read_bytes())
    conteudo[len(conteudo) * 3 // 4] ^= 0xFF
    banco.write_bytes(bytes(conteudo))

    resultado = _rodar("restaurar.sh", ambiente, f"diario/{banco.name}")

    assert resultado.returncode != 0
    assert _quantos_clientes() == 5000


def test_backup_dos_anexos_cortado_nao_mexe_em_nada(ambiente):
    banco, anexos = _fazer_backup(ambiente)
    _consultar("INSERT INTO cliente (nome) VALUES ('Cliente de depois do backup')")
    novo = Path(ambiente["ANEXOS_DIR"]) / "clientes" / "1" / "aditivo.pdf"
    novo.write_bytes(b"%PDF-1.4 aditivo")
    _cortar(anexos, anexos, 0.5)

    resultado = _rodar("restaurar.sh", ambiente, f"diario/{banco.name}")

    assert resultado.returncode != 0
    assert "anexos" in resultado.stderr
    # Nem o banco foi restaurado nem os anexos atuais foram apagados.
    assert _quantos_clientes() == 5001
    assert novo.exists()


def test_senha_errada_nao_mexe_em_nada(ambiente):
    banco, _ = _fazer_backup(ambiente)
    _consultar("DELETE FROM cliente WHERE id > 10")

    resultado = _rodar(
        "restaurar.sh", {**ambiente, "BACKUP_PASSPHRASE": "outra senha"}, f"diario/{banco.name}"
    )

    assert resultado.returncode != 0
    assert _quantos_clientes() == 10


def test_backup_que_falha_nao_deixa_arquivo_pela_metade(ambiente):
    resultado = _rodar("fazer-backup.sh", {**ambiente, "POSTGRES_DB": "banco_que_nao_existe"})

    assert resultado.returncode != 0
    pasta = Path(ambiente["BACKUP_DIR"])
    assert [arquivo.name for arquivo in pasta.rglob("*") if arquivo.is_file()] == []
