# Regras para Agentes de IA — Diretório de Testes

## Regra Principal

**JAMAIS altere código em `src/` para fazer um teste passar.**

Quando um teste falha, a correção deve estar sempre no arquivo de teste. O código de produção em `src/` é a fonte da verdade. Os testes devem refletir o comportamento real do src, não o contrário.

## O que fazer quando um teste falha

- Leia o src e entenda o comportamento real implementado.
- Atualize o teste para refletir esse comportamento.
- Nunca mude rotas, modelos, serviços ou qualquer arquivo em `src/` com o objetivo de fazer o teste passar.

## Exemplos

| Situação | Correto | Errado |
|---|---|---|
| Rota no src é `/school`, teste chama `/schools` | Mudar o teste para `/school` | Mudar o src para `/schools` |
| Src não tem autenticação, teste espera 401 | Remover o teste de 401 | Adicionar auth no src |
| Src retorna campo `name`, teste espera `full_name` | Mudar o teste para `name` | Renomear campo no src |
