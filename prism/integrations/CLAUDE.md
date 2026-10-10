# Integration rules

- Opt in per project and user. Disabled, paused or unregistered hooks do no work.
- Installers only render configuration; core never assumes a particular agent.
- Declare every file change in plan(), including support files.
- Install twice without duplicates. Uninstall restores backed-up user content.
- Managed blocks preserve all surrounding text and unrelated hooks/settings.
- Hooks add context or deny; never approve commands or widen permissions.
- Do not enable, scan or globally install PRISM on an agent's initiative.
- Keep descriptions, instructions and installed skill bodies within budgets.
- Test every host's installation, removal and no-consent behavior.

Detailed specifications: [integrations](../../docs/spec/12-integrations.md),
[skills](../../docs/spec/13-skills.md).
