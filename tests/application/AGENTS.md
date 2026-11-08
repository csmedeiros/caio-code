# tests/application/

Testes da camada de aplicação. Espelham `src/caio_code/application/`.

## Invariantes

- Tudo offline e determinístico: provedor `stub`, `FixedClock`,
  `SequentialIdentifiers`, workspaces em `tmp_path`. Nenhum teste toca rede,
  relógio de parede ou credencial real.
- Eventos são assertados pela ordem de publicação (`EventRecorder`), não por
  contagens soltas: `RunStarted` primeiro, `RunFinished` último.
