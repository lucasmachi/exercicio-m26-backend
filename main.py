from contextlib import asynccontextmanager
import json
import secrets
import redis.asyncio as redis
from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


CHAVE_CACHE_LIVROS = "livros"
TTL_CACHE_LIVROS = 60  #tempo de expiração do cache em segundos

MEU_USUARIO = "admin"
MINHA_SENHA = "admin"
DATABASE_URL = "sqlite:///./livros.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(  #cria o cliente que será compartilhado por todos os endpoints
        "redis://localhost:6379/0",  #endereço corresponde a própria máquina
        decode_responses=True  #leituras retornam texto
    )

    try:
        await app.state.redis.ping()  #verifica comunicação API e redis
        yield
    finally:
        await app.state.redis.aclose()  #encerra cliente quando API para


app = FastAPI(
    lifespan=lifespan,
    title="API Livros",
    description="API para gerenciar livros. Adicione, atualize, delete, e confira quais livros estão na sua biblioteca pessoal :)",
    version="2.0.0",
    contact={
        "name": "Lucas Machi",
        "email": "lucascolafati@gmail.com"
    }
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
security = HTTPBasic()


class LivrosDB(Base):
    __tablename__ = "tabela_livros"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, index=True)
    autor = Column(String, index=True)


class Livro(BaseModel):
    titulo: str
    autor: str


Base.metadata.create_all(bind=engine)


def sessao_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def autenticar_usuario(
    credentials: HTTPBasicCredentials = Depends(security)
):
    is_user_correct = secrets.compare_digest(
        credentials.username, MEU_USUARIO
    )
    is_password_correct = secrets.compare_digest(
        credentials.password, MINHA_SENHA
    )

    if not (is_user_correct and is_password_correct):
        raise HTTPException(
            status_code=401,
            detail="Usuário ou senha inválidos",
            headers={"WWW-Authenticate": "Basic"}
        )


def livro_para_dict(livro: LivrosDB) -> dict:
    return {
        "id": livro.id,
        "titulo": livro.titulo,
        "autor": livro.autor,
    }


#salva a lista de livros no redis por 60seg
async def salvar_livros_redis(livros: list[dict]) -> None:  #list[dict] indica que a função espera uma lista de livros representados como dicionarios
    livros_em_json = json.dumps(livros, ensure_ascii=False)  #json.dumps transforma a lista em texto*

    await app.state.redis.set(  #usa o cliente compartilhado criado abaixo dos imports
        CHAVE_CACHE_LIVROS,
        livros_em_json,
        ex=TTL_CACHE_LIVROS
    )


#deleta a lista de livros armazenada em cache no redis
#apagar a chave faz com que a próxima consulta busque sempre dados atualizados na fonte original
async def deletar_livros_redis(livros: list[dict]) -> None:
    await app.state.redis.delete(CHAVE_CACHE_LIVROS)


@app.post("/adiciona")
async def adicionar_livro(
    livro: Livro,
    db: Session = Depends(sessao_db),
    credentials: HTTPBasicCredentials = Depends(autenticar_usuario)
):
    def salvar_no_banco():
        livro_existente = db.query(LivrosDB).filter(
            LivrosDB.titulo == livro.titulo,
            LivrosDB.autor == livro.autor
        ).first()

        if livro_existente:
            raise HTTPException(
                status_code=400,
                detail="Esse livro já existe no banco de dados!"
            )

        novo_livro = LivrosDB(
            titulo=livro.titulo,
            autor=livro.autor
        )
        db.add(novo_livro)
        db.commit()
        db.refresh(novo_livro)
        return livro_para_dict(novo_livro)

    novo_livro = await run_in_threadpool(salvar_no_banco)
    await deletar_livros_redis([])
    return {"mensagem": "Livro adicionado com sucesso", "livro": novo_livro}


@app.get("/livros")
async def listar_livros(
    db: Session = Depends(sessao_db),
    credentials: HTTPBasicCredentials = Depends(autenticar_usuario)
):
    livros_em_cache = await app.state.redis.get(CHAVE_CACHE_LIVROS)

    if livros_em_cache is not None:
        return json.loads(livros_em_cache)

    def buscar_no_banco():
        livros = db.query(LivrosDB).order_by(LivrosDB.id).all()
        return [livro_para_dict(livro) for livro in livros]

    livros = await run_in_threadpool(buscar_no_banco)
    await salvar_livros_redis(livros)
    return livros


@app.put("/atualiza/{id_livro}")
async def atualizar_livro(
    id_livro: int,
    livro: Livro,
    db: Session = Depends(sessao_db),
    credentials: HTTPBasicCredentials = Depends(autenticar_usuario)
):
    def atualizar_no_banco():
        livro_atualizado = db.query(LivrosDB).filter(
            LivrosDB.id == id_livro
        ).first()

        if not livro_atualizado:
            raise HTTPException(
                status_code=404,
                detail="Esse livro não existe no banco de dados!"
            )

        livro_atualizado.titulo = livro.titulo
        livro_atualizado.autor = livro.autor
        db.commit()
        db.refresh(livro_atualizado)
        return livro_para_dict(livro_atualizado)

    livro_atualizado = await run_in_threadpool(atualizar_no_banco)
    await deletar_livros_redis([])
    return {"mensagem": "Livro atualizado com sucesso", "livro": livro_atualizado}


@app.delete("/deleta/{id_livro}")
async def deletar_livro(
    id_livro: int,
    db: Session = Depends(sessao_db),
    credentials: HTTPBasicCredentials = Depends(autenticar_usuario)
):
    def deletar_do_banco():
        livro_deletado = db.query(LivrosDB).filter(
            LivrosDB.id == id_livro
        ).first()

        if not livro_deletado:
            raise HTTPException(
                status_code=404,
                detail="Esse livro não existe no banco de dados!"
            )

        db.delete(livro_deletado)
        db.commit()

    await run_in_threadpool(deletar_do_banco)
    await deletar_livros_redis([])
    return {"mensagem": "Livro deletado com sucesso!"}