# ContractScan GitHub Action

Scan Solidity smart contracts for security vulnerabilities in your CI/CD pipeline.

ContractScan uses [Slither](https://github.com/crytic/slither) static analysis with AI-enhanced reporting to detect vulnerabilities in your smart contracts on every push and pull request.

## Usage

```yaml
- name: Scan smart contracts
  uses: h33min/contractscan-action@v1
  with:
    api-key: ${{ secrets.CONTRACTSCAN_API_KEY }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `api-key` | Yes | — | ContractScan API key. Store as a repository secret. |
| `api-url` | No | `https://contract-scanner.raccoonworld.xyz` | ContractScan API base URL |
| `path` | No | `**/*.sol` | Glob pattern for Solidity files to scan |
| `fail-on` | No | `Critical` | Minimum severity that fails CI (`Critical`, `High`, `Medium`, `Low`) |
| `report-format` | No | `markdown` | Output format: `markdown` or `json` |
| `max-files` | No | `20` | Maximum number of files to scan per run |

## Outputs

| Output | Description |
|--------|-------------|
| `findings-count` | Total number of findings |
| `critical-count` | Number of Critical severity findings |
| `passed` | `true` if all scans passed the threshold |

## Example Workflow

See [example-workflow.yml](./example-workflow.yml) for a complete example including PR comments.

## Get an API Key

Visit [ContractScan](https://contract-scanner.raccoonworld.xyz) to create an account and generate an API key.

## License

MIT
