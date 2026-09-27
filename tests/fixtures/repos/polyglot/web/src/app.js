const { checkout } = require("./cart");
// TODO: wire the real payment provider
function main() {
  return checkout(null);
}
module.exports = { main };
