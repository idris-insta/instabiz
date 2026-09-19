from instabiz.overrides.ib_settings import ModuleSettings


class IBPrintSettings(ModuleSettings):
	def on_update(self):
		super().on_update()
		if self.has_value_changed("print_default_layout") and self.print_default_layout:
			from instabiz.overrides.print_families import apply_defaults

			apply_defaults(self.print_default_layout)
