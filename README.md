# ContractScan GitHub Action

Scan Solidity smart contracts for security vulnerabilities in your CI/CD pipeline.

ContractScan uses [Slither](https://github.com/crytic/slither) static analysis with AI-enhanced reporting to detect vulnerabilities in your smart contracts on every push and pull request.

## Usage

```yaml
# Free tier (no API key needed):
- name: Scan smart contracts
  uses: h33min/contractscan-action@v1

# With API key (unlimited scans):
- name: Scan smart contracts
  uses: h33min/contractscan-action@v1
  with:
    api-key: ${{ secrets.CONTRACTSCAN_API_KEY }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `api-key` | No | — | ContractScan API key. Optional for free tier. Store as a repository secret for paid plans. |
| `api-url` | No | `https://contract-scanner.raccoonworld.xyz` | ContractScan API base URL |
| `path` | No | `**/*.sol` | Glob pattern for Solidity files to scan |
| `fail-on` | No | `Critical` | Minimum severity that fails CI (`Critical`, `High`, `Medium`, `Low`) |
| `report-format` | No | `markdown` | Output format: `markdown` or `json` |
| `max-files` | No | `300` | Maximum number of files to scan per run |

## Features

- **ZIP bundling**: Automatically bundles your Solidity source files and dependency directories (`node_modules/`, `lib/`, `dependencies/`) into a single archive for correct import resolution
- **Free tier**: No API key required. Daily usage limits apply.
- **Multi-engine**: Slither static analysis + AI vulnerability detection
- **Real hack references**: Cross-references findings with real DeFi exploit patterns

## Outputs

| Output | Description |
|--------|-------------|
| `findings-count` | Total number of findings |
| `critical-count` | Number of Critical severity findings |
| `passed` | `true` if all scans passed the threshold |

## Example Workflow

See [example-workflow.yml](./example-workflow.yml) for a complete example including PR comments.

## Get an API Key

Free tier works without an API key. For unlimited scans, visit [ContractScan](https://contract-scanner.raccoonworld.xyz) to generate an API key.

## License

MIT
