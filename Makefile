PREFIX ?= /usr/local
BINDIR = $(PREFIX)/bin
DATADIR = $(PREFIX)/share
ICONDIR = $(DATADIR)/icons/hicolor
APPSDIR = $(DATADIR)/applications

.PHONY: install uninstall run

install:
	@echo "Installing NetGuard..."
	install -d $(DESTDIR)$(BINDIR)
	install -m 755 main.py $(DESTDIR)$(BINDIR)/netguard
	install -d $(DESTDIR)$(ICONDIR)/scalable/apps
	install -m 644 assets/netguard.svg $(DESTDIR)$(ICONDIR)/scalable/apps/netguard.svg
	install -d $(DESTDIR)$(APPSDIR)
	@sed 's|Exec=.*|Exec=$(BINDIR)/netguard|' netguard.desktop > $(DESTDIR)$(APPSDIR)/netguard.desktop
	gtk-update-icon-cache -f -t $(DESTDIR)$(ICONDIR) 2>/dev/null || true
	update-desktop-database $(DESTDIR)$(APPSDIR) 2>/dev/null || true
	@echo "Installed. Run 'netguard' to start."

uninstall:
	@echo "Uninstalling NetGuard..."
	rm -f $(DESTDIR)$(BINDIR)/netguard
	rm -f $(DESTDIR)$(ICONDIR)/scalable/apps/netguard.svg
	rm -f $(DESTDIR)$(APPSDIR)/netguard.desktop
	gtk-update-icon-cache -f -t $(DESTDIR)$(ICONDIR) 2>/dev/null || true
	update-desktop-database $(DESTDIR)$(APPSDIR) 2>/dev/null || true
	@echo "Uninstalled."

run:
	python3 main.py
