# API de livros com cache Redis

API em FastAPI para cadastrar, listar, atualizar e excluir livros. O SQLite guarda os dados; o Redis guarda temporariamente o resultado de `GET /livros` por 60 segundos. Após uma escrita no banco, a API apaga o cache para que a consulta seguinte leia os dados atualizados.

## Requisitos

- Python 3.10 ou superior
- Um servidor Redis local ou em contêiner
- O arquivo `main.py` na mesma pasta em que estes comandos serão executados

O arquivo `livros.db` é criado automaticamente na pasta de execução da API. Para testar localmente, a autenticação HTTP Basic usa usuário `admin` e senha `admin`, definidos em `main.py`. Essas credenciais são apenas para demonstração.

## Instalação

Instale os pacotes Python:

```bash
python -m pip install fastapi uvicorn sqlalchemy redis
```

Inicie o Redis **na mesma máquina em que a API será executada**, escolhendo uma opção:

```bash
# Docker

docker run -d --name livros-redis -p 6379:6379 redis:7
```

```bash
# Podman (use no lugar do comando Docker acima)

podman run -d --name livros-redis -p 6379:6379 docker.io/library/redis:7
```

Se já tiver o servidor Redis instalado localmente, inicie-o com `redis-server` em vez de criar um contêiner. O endereço configurado em `main.py` é `redis://localhost:6379/0`. Se a própria API rodar dentro de um contêiner, `localhost` apontará para esse contêiner: ajuste o endereço Redis no código para o nome do serviço Redis na rede de contêineres.

Inicie a API em outro terminal:

```bash
uvicorn main:app --reload
```

A documentação interativa fica em <http://localhost:8000/docs>. Nas rotas protegidas, use o botão **Authorize** com `admin` / `admin`.

## Teste do cache

Os comandos a seguir usam um terminal Bash (Linux, macOS, WSL ou Git Bash). No PowerShell, use `curl.exe` no lugar de `curl` e adapte as aspas do JSON. Execute-os com a API e o Redis em funcionamento.

1. Consulte a lista. Em uma base nova, o resultado deve ser `[]`. Essa primeira chamada busca no SQLite e salva o resultado, inclusive quando a lista está vazia:

   ```bash
   curl -u admin:admin http://localhost:8000/livros
   ```

2. Confira a chave e seu tempo restante de expiração. Para Docker, execute:

   ```bash
   docker exec livros-redis redis-cli GET livros
   docker exec livros-redis redis-cli TTL livros
   ```

   Com Podman, substitua `docker` por `podman`. Com Redis instalado localmente, use `redis-cli GET livros` e `redis-cli TTL livros`. O `GET` deve mostrar um JSON; o `TTL` deve mostrar um valor entre 0 e 60 segundos. Após 60 segundos, a chave expira e uma nova chamada à API a recria.

3. Cadastre um livro:

   ```bash
   curl -u admin:admin -X POST http://localhost:8000/adiciona \
     -H 'Content-Type: application/json' \
     -d '{"titulo":"Dom Casmurro","autor":"Machado de Assis"}'
   ```

   Agora `docker exec livros-redis redis-cli GET livros` deve mostrar `(nil)`: a escrita no SQLite apagou o cache. Use a variante Podman ou local indicada acima, conforme sua instalação.

4. Consulte novamente:

   ```bash
   curl -u admin:admin http://localhost:8000/livros
   ```

   A resposta deve conter o livro cadastrado. `GET livros` no Redis deve voltar a mostrar uma lista JSON com esse livro. Outra chamada a `GET /livros`, antes de o TTL acabar, lê essa lista do cache.

5. Teste atualização e exclusão. O exemplo supõe que o livro criado recebeu ID `1`; confira o ID na resposta do cadastro e ajuste-o se necessário:

   ```bash
   curl -u admin:admin -X PUT http://localhost:8000/atualiza/1 \
     -H 'Content-Type: application/json' \
     -d '{"titulo":"Dom Casmurro","autor":"Machado de Assis (edição revisada)"}'

   curl -u admin:admin http://localhost:8000/livros

   curl -u admin:admin -X DELETE http://localhost:8000/deleta/1

   curl -u admin:admin http://localhost:8000/livros
   ```

   Após cada `PUT` ou `DELETE`, confira com `redis-cli GET livros` que a chave desapareceu **antes** da próxima chamada a `GET /livros`. A consulta seguinte deve trazer o estado atualizado do SQLite e recriar o cache.

## Comparar tempos de resposta

Para comparar uma chamada sem cache com outra com cache, limpe apenas a chave `livros` no Redis e faça duas consultas seguidas:

```bash
docker exec livros-redis redis-cli DEL livros
curl -s -o /dev/null -w 'Sem cache: %{time_total}s\n' -u admin:admin http://localhost:8000/livros
curl -s -o /dev/null -w 'Com cache: %{time_total}s\n' -u admin:admin http://localhost:8000/livros
```

Substitua `docker exec livros-redis redis-cli DEL livros` por `podman exec livros-redis redis-cli DEL livros` ou `redis-cli DEL livros` conforme o modo de instalação. Faça as consultas com menos de 60 segundos de intervalo. Como o SQLite e a lista são pequenos e locais, uma única medição pode oscilar; a existência, expiração e remoção da chave Redis são a verificação principal do funcionamento do cache.
