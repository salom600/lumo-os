# Lumo OS top-level Makefile
SHELL := /bin/bash
BUILD := build

.PHONY: debs iso test lint clean

debs:
	./scripts/build-debs.sh

iso: debs
	sudo ./scripts/build-iso.sh

lint:
	./tests/check-all.sh

test: iso
	./scripts/tests/qemu-smoke.sh $(BUILD)/*.iso

clean:
	rm -rf $(BUILD)
