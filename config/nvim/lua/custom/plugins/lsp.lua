return {
  {
    "neovim/nvim-lspconfig",
    config = function()
      -- Define LSP keymaps that will be set when LSP attaches
      vim.api.nvim_create_autocmd("LspAttach", {
        callback = function(args)
          local bufnr = args.buf
          local client = vim.lsp.get_client_by_id(args.data.client_id)

          local bufmap = function(mode, lhs, rhs, desc)
            vim.keymap.set(mode, lhs, rhs, { buffer = bufnr, desc = desc })
          end

          bufmap("n", "K", vim.lsp.buf.hover, "LSP Hover")
          bufmap("n", "gd", vim.lsp.buf.definition, "Go to Definition")
          bufmap("n", "<leader>e", vim.diagnostic.open_float, "Show Diagnostic")
          bufmap("n", "[d", vim.diagnostic.goto_prev, "Prev Diagnostic")
          bufmap("n", "]d", vim.diagnostic.goto_next, "Next Diagnostic")
        end,
      })

      -- Auto-detect Python virtual environment
      local function get_python_path()
        -- Check for common venv locations
        local venv_paths = {
          vim.fn.getcwd() .. "/.venv/bin/python",
          vim.fn.getcwd() .. "/venv/bin/python",
          vim.fn.getcwd() .. "/.env/bin/python",
        }
        
        for _, path in ipairs(venv_paths) do
          if vim.fn.executable(path) == 1 then
            return path
          end
        end
        
        -- Fallback to system Python
        return vim.fn.exepath("python3") or vim.fn.exepath("python")
      end

      -- Configure Pyright LSP
      vim.lsp.config.pyright = {
        cmd = { "pyright-langserver", "--stdio" },
        filetypes = { "python" },
        root_markers = {
          "pyproject.toml",
          "setup.py",
          "setup.cfg",
          "requirements.txt",
          "Pipfile",
          "pyrightconfig.json",
          ".git",
        },
        settings = {
          python = {
            pythonPath = get_python_path(),
            analysis = {
              autoSearchPaths = true,
              diagnosticMode = "openFilesOnly",
              useLibraryCodeForTypes = true,
            },
          },
        },
      }

      -- Enable Pyright
      vim.lsp.enable("pyright")
    end,
  },
}

