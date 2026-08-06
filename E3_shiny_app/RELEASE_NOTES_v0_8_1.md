# ARIA plant E3 Shiny reporter v0.8.1

Version 0.8.1 is a source-loading compatibility hotfix for the v0.8.0
application. It replaces a compact single-expression `tryCatch()` error handler
with an explicit braced function body in `module_result_section.R`. This avoids
the Shiny application loader reporting a possible missing comma while sourcing
the package-style `R/` directory.

It also wraps the two expression-filter column layouts in a single
`shiny::tagList()`. The layouts had been placed directly inside one conditional
branch and separated by a comma, which prevented R from parsing the module.

The launcher now passes the explicit `app.R` file to `shiny::runApp()` instead
of the package root. The application therefore follows its declared source
order without Shiny also auto-loading the package-style `R/` directory.

The scientific queries, display logic, input data contracts and workflow
results are unchanged.

The complete `testthat` suite must be executed in the `e3_shiny_app` R
environment before release.
