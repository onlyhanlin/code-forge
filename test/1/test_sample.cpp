// Test file for c-cpp-code-checker verification
// Contains deliberate issues to verify tool detection

int main() {
    // Style issue: using namespace in global scope
      using namespace std;

    // Uninitialized variable
    int uninit_var;
    int result = uninit_var + 5;

    // Memory leak
    int* leaked = new int[100];
    // No delete — memory leak

    // Null pointer dereference potential
    int* ptr = nullptr;
     *ptr = 42;  // Uncomment to test null pointer detection

    // Buffer overflow potential
    char buffer[10];
    //strcpy(buffer, "This string is way too long for the buffer");

    return 0;
}