pragma solidity ^0.5.16;

interface Controller {
    function vaults(address) external view returns (address);
}
