# Publish these docs

The repository includes a searchable MkDocs Material site and a GitHub Actions workflow.
It is the browsable manual for the project. The source remains ordinary Markdown under
`docs_site/`, so documentation changes are reviewed with code changes.

## One-time GitHub setting

After the release is pushed:

1. Open the repository on GitHub.
2. Select **Settings**.
3. Select **Pages** under **Code and automation**.
4. Under **Build and deployment**, set **Source** to **GitHub Actions**.
5. Run the `Documentation` workflow or push a documentation change to `main`.

The published address is:

```text
https://peterthorpe5.github.io/E3_project_draft/
```

GitHub's current Pages guidance recommends a custom Actions workflow when using a static
site generator other than Jekyll. The supplied workflow builds MkDocs, uploads the static
artifact and deploys it through the `github-pages` environment.

## Preview locally

```bash
python -m pip install --requirement requirements-docs.txt
mkdocs serve
```

Open the local address printed by MkDocs. Search runs in the browser.

## Validate without serving

```bash
mkdocs build --strict
```

The workflow also runs this strict build for pull requests but deploys only non-pull-request
events.

## Public-data warning

GitHub Pages is public. Do not place controlled, private, unpublished or sensitive data
under `docs_site/` or in the generated site.

## Primary references

- [GitHub: configuring a Pages publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [MkDocs configuration](https://www.mkdocs.org/user-guide/configuration/)
- [Material for MkDocs setup](https://squidfunk.github.io/mkdocs-material/setup/)
