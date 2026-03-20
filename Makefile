CXX      := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -Wpedantic
TARGET   := simulation/simulator
SRC      := simulation/simulator.cpp

.PHONY: all clean test evaluate full smoke

## Build the C++ simulator binary
all: $(TARGET)

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<
	@echo "  ✓ Built $(TARGET)"

## Quick smoke-test: single 5×5 open-field run (no scenario file needed)
smoke: $(TARGET)
	@echo "── Smoke test ──────────────────────────────────────────────────"
	./$(TARGET) --id smoke_test --width 5 --height 5 \
	            --start-x 0 --start-y 0 --goal-x 4 --goal-y 4 \
	            --max-steps 20 --behavior greedy --obstacles ""
	@echo ""
	@echo "── Reckless smoke (expects COLLISION) ─────────────────────────"
	./$(TARGET) --id smoke_reckless --width 5 --height 5 \
	            --start-x 0 --start-y 0 --goal-x 4 --goal-y 4 \
	            --max-steps 20 --behavior reckless --obstacles "2,2" || true
	@echo ""

## Run the full scenario test suite
test: $(TARGET)
	python3 runner/test_runner.py

## Generate evaluation report from latest run
evaluate:
	python3 runner/evaluate.py

## Historical trend across all recorded runs
trend:
	python3 runner/evaluate.py --all --trend

## Build + test + evaluate in one shot
full: $(TARGET) test evaluate

## Remove build artefacts and results database
clean:
	rm -f $(TARGET) results.db
	@echo "  ✓ Cleaned"
