# src/caio_code/state/

Estado durável entre turnos e sessões. É o que impede o agente de recomeçar do zero quando o
contexto é descartado.

## Invariantes

- Estado é **dado serializável**, não objeto vivo: JSON, versionado, com campo `version`.
- Escrita atômica: arquivo temporário no mesmo diretório e `os.replace`. Nunca escrever no
  lugar.
- Leitura de estado corrompido levanta erro tipado e preserva o arquivo original; não
  sobrescreve para "consertar".
- Nenhum caminho fora do diretório de estado configurado.
- O estado não guarda segredo nem transcript bruto.

## O que entra no estado

Progresso da tarefa, decisões tomadas, arquivos tocados, pendências. O que o agente precisa para
continuar — não o histórico inteiro da conversa.

## O que não entra aqui

Política de contexto (isso é `context/`), cache de provedor, log de execução.