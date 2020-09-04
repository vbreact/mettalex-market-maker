pragma solidity ^0.5.16;

interface MettalexVault {
    function collateralPerUnit()
        external
        view
        returns (uint256 _collateralPerUnit);

    function collateralFeePerUnit()
        external
        view
        returns (uint256 _collateralFeePerUnit);

    function priceFloor() external view returns (uint256 _priceFloor);

    function priceSpot() external view returns (uint256 _priceSpot);

    function priceCap() external view returns (uint256 _priceCap);

    function mintPositions(uint256 qtyToMint) external;

    function redeemPositions(uint256 qtyToRedeem) external;

    function mintFromCollateralAmount(uint256 _collateralAmount) external;
}
